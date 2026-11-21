import unittest
from unittest.mock import Mock

from github import GithubException

from gh_transcript_fetch.publishing import commit_file


class PublishingTests(unittest.TestCase):
    def test_creates_branch_when_github_returns_generic_404(self):
        repo = Mock()
        base = Mock()
        base.commit.sha = "base-sha"
        repo.get_branch.side_effect = [
            GithubException(404, {"message": "Branch not found"}, None),
            base,
        ]
        repo.get_contents.side_effect = GithubException(404, {"message": "Not Found"}, None)
        branch = "transcripts/2026-11-21-episode"
        filename = "2026-11-21-episode.md"

        path = commit_file(repo, filename, "Transcript", branch)

        self.assertEqual(path, f"site/transcripts/{filename}")
        repo.create_git_ref.assert_called_once_with(ref=f"refs/heads/{branch}", sha="base-sha")
        repo.create_file.assert_called_once_with(
            path, f"Add transcript: {filename}", "Transcript", branch=branch
        )
