from collections import defaultdict, Counter
import pygit2

def commits_per_email(repo_path: str, ref: str = "HEAD", drop_merges: bool = False):
    git_dir = pygit2.discover_repository(repo_path)
    repo = pygit2.Repository(git_dir)

    target = repo.revparse_single(ref).id
    walker = repo.walk(target, pygit2.GIT_SORT_TOPOLOGICAL | pygit2.GIT_SORT_TIME)

    counts = Counter()
    names_seen = defaultdict(Counter)

    for commit in walker:
        if drop_merges and len(commit.parents) > 1:
            continue

        email = (commit.author.email or "unknown").strip().lower()
        name = (commit.author.name or "unknown").strip()

        counts[email] += 1
        names_seen[email][name] += 1

    # build nice display: pick most common name for each email
    rows = []
    for email, n in counts.most_common():
        best_name, _ = names_seen[email].most_common(1)[0]
        rows.append((n, best_name, email))

    return rows

rows = commits_per_email("/Users/Ziyan/Documents/GitHub/Malware-Analysis")
for n, name, email in rows[:20]:
    print(f"{n:6d}  {name} <{email}>")