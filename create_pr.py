import os
import re
import requests
import datetime
from github import Github
from env import *

GITHUB_TOKEN = os.environ['GH_TOKEN']

REPO_NAME = "josherich/blog"
BRANCH_NAME = "gh-pages"
POSTS_FOLDER = "_posts"

BASE_URL = "https://api.github.com/repos"

def get_template():
    """Fetches the template markdown content."""
    template = """---
layout: post
title: "{title}"
date: {date} 00:00:01
categories: podcast
tags: [podcast_script]
---

{content}
"""
    return template

def normalize_title_to_branch(title: str) -> str:
    branch_name = title.lower()

    # Replace non-alphanumeric characters (except spaces) with empty string
    branch_name = re.sub(r"[^\w\s-]", "", branch_name)

    # Replace spaces and underscores with hyphens
    branch_name = re.sub(r"[\s_]+", "-", branch_name)

    branch_name = branch_name.strip("-")
    return branch_name

def create_markdown_file(title, transcription, date):
    """Creates a new markdown file content using the transcription."""
    normalized_title = normalize_title_to_branch(title)
    filename = f"{date}-{normalized_title}.md"
    content = get_template().format(title=title, date=date, content=transcription)
    branch_name = f"{date}-{normalized_title}"
    return filename, content, branch_name

def get_repo():
    """Authenticates with GitHub and returns the repository object."""
    github = Github(GITHUB_TOKEN)
    return github.get_repo(REPO_NAME)

def commit_file(repo, filename, content, branch_name):
    """Commits the new blog post markdown file to the GitHub repo and create a new branch for pr."""
    file_path = f"{POSTS_FOLDER}/{filename}"

    base_branch = repo.get_branch(BRANCH_NAME)
    repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=base_branch.commit.sha)

    print(f"Creating file commit: {file_path}, branch: {branch_name}\n\n{content}")
    repo.create_file(
        file_path,
        f"Add new transcript post: {filename}",
        content,
        branch=branch_name
    )
    return file_path

def create_pull_request(repo, filename, branch_name):
    """Creates a pull request to merge the new blog post into the repo."""
    title = f"New Blog Post: {filename}"
    body = "This is an auto-generated blog post from transcription."

    pr = repo.create_pull(
        title=title,
        body=body,
        head=branch_name,
        base=BRANCH_NAME
    )
    return pr.html_url

def create_branch_and_pr(title, transcription, date):
    repo = get_repo()
    filename, content, branch_name = create_markdown_file(title, transcription, date)

    file_path = commit_file(repo, filename, content, branch_name)
    pr_url = create_pull_request(repo, filename, branch_name)

    return pr_url, file_path

def format_pr_content(title, url, transcript, rewritten, toc):
    return f'\n[{title.replace("|", " ")}]({url})\n\n' + transcript + '\n\n---\n\n > This is an experimental rewrite\n' + rewritten + f'\n\n<script>window.tocIndex = {toc}\n</script>'

if __name__ == "__main__":
    title = "Test Podcast"
    transcription = "This is a test podcast transcription."
    pr_url, file_path = create_branch_and_pr(title, transcription, '2025-01-01')
    print(f"PR URL: {pr_url}")
    print(f"File Path: {file_path}")
