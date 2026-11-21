from datetime import date as calendar_date
import hashlib
import json
import os
import re

from github import Github, GithubException, UnknownObjectException

REPO_NAME = "josherich/gh-pages-transcript"
BRANCH_NAME = "main"
POSTS_FOLDER = "site/transcripts"


def normalize_title_to_branch(title: str) -> str:
    title = re.sub(r"[^\w\s-]", "", title.lower())
    return re.sub(r"[-\s_]+", "-", title).strip("-")


def create_markdown_file(title, transcription, date, channel_title=None):
    date = calendar_date.fromisoformat(date).isoformat()
    slug = normalize_title_to_branch(title)
    if not slug or len(slug.encode("utf-8")) > 220:
        prefix = slug.encode("utf-8")[:200].decode("utf-8", errors="ignore").rstrip("-")
        digest = hashlib.sha256(title.encode("utf-8")).hexdigest()[:12]
        slug = f"{prefix or 'episode'}-{digest}"

    filename = f"{date}-{slug}.md"
    categories = ["podcast", channel_title or "untitled"]
    content = (
        f"---\ntitle: {json.dumps(title, ensure_ascii=False)}\n"
        f"date: {date}\n"
        f"slug: {date}-{slug}\n"
        f"categories: {json.dumps(categories, ensure_ascii=False)}\n"
        f"tags: [podcast_script]\n---\n\n{transcription}\n"
    )
    return filename, content, f"transcripts/{date}-{slug}"


def get_repo():
    github = Github(os.environ["GH_TOKEN"])
    return github.get_repo(REPO_NAME)


def commit_file(repo, filename, content, branch_name):
    """Create or resume a branch with the generated transcript."""
    file_path = f"{POSTS_FOLDER}/{filename}"

    try:
        repo.get_branch(branch_name)
    except UnknownObjectException:
        base_branch = repo.get_branch(BRANCH_NAME)
        try:
            repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=base_branch.commit.sha)
        except GithubException as error:
            if error.status != 422:
                raise
            repo.get_branch(branch_name)

    try:
        repo.get_contents(file_path, ref=branch_name)
    except UnknownObjectException:
        try:
            repo.create_file(file_path, f"Add transcript: {filename}", content, branch=branch_name)
        except GithubException as error:
            if error.status not in (409, 422):
                raise
            repo.get_contents(file_path, ref=branch_name)
    return file_path


def find_pull_request(repo, branch_name):
    for pr in repo.get_pulls(state="all", head=f"{repo.owner.login}:{branch_name}", base=BRANCH_NAME):
        if pr.state == "open" or pr.merged_at:
            return pr.html_url
    return None


def create_pull_request(repo, filename, branch_name):
    try:
        return repo.create_pull(
            title=f"Add transcript: {filename}",
            body="Merge this pull request to publish the transcript on the podcast archive.",
            head=branch_name,
            base=BRANCH_NAME,
        ).html_url
    except GithubException as error:
        if error.status == 422 and (existing := find_pull_request(repo, branch_name)):
            return existing
        raise


def create_branch_and_pr(title, transcription, date, channel_title=None):
    repo = get_repo()
    filename, content, branch_name = create_markdown_file(title, transcription, date, channel_title)
    existing = find_pull_request(repo, branch_name)
    if existing:
        return existing, f"{POSTS_FOLDER}/{filename}"

    file_path = commit_file(repo, filename, content, branch_name)
    return create_pull_request(repo, filename, branch_name), file_path


def format_pr_content(title, url, transcript, rewritten, toc, faq):
    title = title.replace("[", r"\[").replace("]", r"\]")
    toc = json.dumps(json.loads(toc) if toc else None, ensure_ascii=False).replace("<", r"\u003c")
    faq = json.dumps(json.loads(faq) if faq else None, ensure_ascii=False).replace("<", r"\u003c")
    return (
        f"\n[{title}](<{url}>)\n\n{transcript}\n\n"
        f"<script>window.tocIndex = {toc};\nwindow.faq = {faq};\n</script>"
    )
