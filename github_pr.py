import base64
from dataclasses import dataclass
from typing import Optional, Any, Dict
import httpx


@dataclass
class PRResult:
    branch_name: str
    pr_number: int
    pr_url: str


class GitHubAPIError(RuntimeError):
    def __init__(self, method: str, path: str, status_code: int, payload: dict):
        self.method = method
        self.path = path
        self.status_code = status_code
        self.payload = payload
        msg = payload.get("message") or payload.get("error") or "GitHub API error"
        super().__init__(f"{method} {path} -> {status_code}: {msg}")


class GitHubPR:
    def __init__(
        self,
        token: Optional[str],
        owner: str,
        repo: str,
        api_base: str = "https://api.github.com",
    ):
        self.token = token or ""
        self.owner = owner
        self.repo = repo
        self.api_base = api_base.rstrip("/")

    def _headers(self):
        h = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "determa-orchestrator",
        }
        if self.token:
            # גם "token <PAT>" עובד. "Bearer" עובד לטוקנים מודרניים/FGPAT.
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def _req_json(self, method: str, path: str, *, json_body=None):
        url = f"{self.api_base}{path}"
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.request(method, url, headers=self._headers(), json=json_body)

        if r.status_code >= 400:
            try:
                payload = r.json()
            except Exception:
                payload = {"raw": r.text}
            raise GitHubAPIError(method, path, r.status_code, payload)

        # חלק מה-endpoints (DELETE) יכולים להחזיר גוף ריק; פה אנחנו עובדים עם json endpoints.
        return r.json()

    async def _ensure_trigger_commit(self, branch_name: str, *, task_id: str, exec_id: str) -> None:
        """
        יוצר/מעדכן קובץ trigger כדי להבטיח שיש קומיט ב-branch (שלא יהיה "No commits between").
        עובד גם אם הקובץ כבר קיים (מעדכן עם sha).
        """
        path = ".determa-trigger"  # אפשר גם להפוך לייחודי אם תרצה: f".determa-trigger-{task_id}-{exec_id}"
        content_txt = f"trigger task={task_id} exec={exec_id}\n"
        content_b64 = base64.b64encode(content_txt.encode("utf-8")).decode("ascii")

        put_path = f"/repos/{self.owner}/{self.repo}/contents/{path}"

        # נסה ליצור בלי sha (create)
        try:
            await self._req_json(
                "PUT",
                put_path,
                json_body={
                    "message": "chore: trigger",
                    "content": content_b64,
                    "branch": branch_name,
                },
            )
            return
        except GitHubAPIError as e:
            # אם הקובץ כבר קיים, GitHub דורש sha כדי לעדכן.
            msg = (e.payload.get("message") or "").lower()
            if e.status_code != 422:
                raise
            # שני מצבים נפוצים: "sha" wasn't supplied / "already exists"
            if ("sha" in msg) or ("already exists" in msg):
                # קח sha נוכחי ואז עדכן
                current = await self._req_json("GET", f"{put_path}?ref={branch_name}")
                file_sha = current.get("sha")
                if not file_sha:
                    # אם המבנה שונה/לא צפוי, פשוט זרוק את השגיאה המקורית
                    raise e
                await self._req_json(
                    "PUT",
                    put_path,
                    json_body={
                        "message": "chore: trigger",
                        "content": content_b64,
                        "branch": branch_name,
                        "sha": file_sha,
                    },
                )
                return
            raise

    async def _get_existing_pr(self, branch_name: str, base_branch: str) -> Optional[PRResult]:
        """
        אם כבר יש PR פתוח מה-branch הזה לבייס הזה, נחזיר אותו במקום להיכשל.
        """
        head = f"{self.owner}:{branch_name}"
        prs = await self._req_json(
            "GET",
            f"/repos/{self.owner}/{self.repo}/pulls?state=open&head={head}&base={base_branch}",
        )
        if isinstance(prs, list) and prs:
            pr = prs[0]
            return PRResult(branch_name=branch_name, pr_number=int(pr["number"]), pr_url=str(pr["html_url"]))
        return None

    async def create_draft_pr_with_trigger(
        self, *, task_id: str, exec_id: str, base_branch: str, title: str, body: str
    ) -> PRResult:
        # 1) base SHA
        ref = await self._req_json("GET", f"/repos/{self.owner}/{self.repo}/git/ref/heads/{base_branch}")
        base_sha = str(ref["object"]["sha"])

        # 2) create branch (אם קיים — להתעלם)
        branch_name = f"determa/task-{task_id}-{exec_id}".replace(":", "-")
        try:
            await self._req_json(
                "POST",
                f"/repos/{self.owner}/{self.repo}/git/refs",
                json_body={"ref": f"refs/heads/{branch_name}", "sha": base_sha},
            )
        except GitHubAPIError as e:
            if e.status_code == 422 and "Reference already exists" in (e.payload.get("message") or ""):
                pass
            else:
                raise

        # 2.5) ודא שיש קומיט ב-branch
        await self._ensure_trigger_commit(branch_name, task_id=task_id, exec_id=exec_id)

        # 3) open draft PR (אם אין קומיטים עדיין/כבר קיים — לטפל)
        try:
            pr = await self._req_json(
                "POST",
                f"/repos/{self.owner}/{self.repo}/pulls",
                json_body={
                    "title": title,
                    "head": branch_name,
                    "base": base_branch,
                    "body": body,
                    "draft": True,
                },
            )
            return PRResult(branch_name=branch_name, pr_number=int(pr["number"]), pr_url=str(pr["html_url"]))

        except GitHubAPIError as e:
            if e.status_code == 422:
                # (a) PR כבר קיים
                msg = e.payload.get("message") or ""
                # GitHub לפעמים מחזיר errors עם message מפורט יותר
                errors = e.payload.get("errors") or []
                errors_text = " ".join(str(x.get("message", "")) for x in errors if isinstance(x, dict))

                if "already exists" in msg.lower() or "already exists" in errors_text.lower():
                    existing = await self._get_existing_pr(branch_name, base_branch)
                    if existing:
                        return existing

                # (b) אין קומיטים בין base ל-head (או שהתזמון מהיר מדי) — תן עוד trigger ואז נסה שוב פעם אחת
                if "No commits between" in errors_text or "no commits between" in errors_text.lower():
                    await self._ensure_trigger_commit(branch_name, task_id=task_id, exec_id=exec_id)
                    pr = await self._req_json(
                        "POST",
                        f"/repos/{self.owner}/{self.repo}/pulls",
                        json_body={
                            "title": title,
                            "head": branch_name,
                            "base": base_branch,
                            "body": body,
                            "draft": True,
                        },
                    )
                    return PRResult(branch_name=branch_name, pr_number=int(pr["number"]), pr_url=str(pr["html_url"]))

            raise