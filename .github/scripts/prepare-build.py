"""Produce the specification/image matrix without interpolating inputs into shell."""
import json
import os
from pathlib import Path
import re
import subprocess


def validate_tag(tag):
    if not isinstance(tag, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", tag):
        raise ValueError(f"Invalid Docker tag: {tag!r}")
    subprocess.run(["git", "check-ref-format", "--branch", tag], check=True, stdout=subprocess.DEVNULL)
    return tag


def open_pull_requests():
    # state=open includes both draft PRs and PRs ready for review.
    pages = json.loads(subprocess.check_output([
        "gh", "api", "--paginate", "--slurp",
        "repos/dataspecer/dataspecer/pulls?state=open&per_page=100",
    ]))
    return [pr for page in pages for pr in page]


def image_exists(image):
    result = subprocess.run(["docker", "manifest", "inspect", image],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if result.returncode == 0:
        return True
    error = result.stderr.strip()
    if any(message in error.lower() for message in
           ("no such manifest", "manifest unknown", "manifest_unknown")):
        print(f"Skipping unpublished image: {image}")
        return False
    raise RuntimeError(f"Could not inspect {image}: {error}")


def main():
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    if os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch":
        inputs = event["inputs"]
        tag = validate_tag(inputs["docker_tag"])
        image = inputs["docker_image"].strip()
        if not image or image.startswith("-") or any(c.isspace() for c in image):
            raise ValueError("docker_image must be a full pullable image reference")
        targets = [{"tag": tag, "image": image, "pr_number": inputs.get("pr_number", "")}]
    else:
        repository = os.environ.get("DOCKER_IMAGE_REPOSITORY", "").strip()
        if not repository or repository.startswith("-") or any(c.isspace() for c in repository):
            raise ValueError("Set the DOCKER_IMAGE_REPOSITORY repository variable")
        tags = json.loads(os.environ.get("PUSH_DOCKER_TAGS", '["branch-main","latest"]'))
        if not isinstance(tags, list) or not tags:
            raise ValueError("PUSH_DOCKER_TAGS must be a nonempty JSON array of tags")
        prs = open_pull_requests()
        pr_tags = dict.fromkeys(validate_tag(f"pr-{pr['number']}") for pr in prs)
        # Match the branch tag sanitization used by the image pipeline and PR comments.
        base_tags = [re.sub(r"[^a-zA-Z0-9_.-]+", "-", f"branch-{pr['base']['ref']}")
                     for pr in prs]
        tags = dict.fromkeys(validate_tag(tag) for tag in [*tags, *pr_tags, *base_tags])
        targets = [{"tag": tag, "image": f"{repository}:{tag}",
                    "pr_number": tag.removeprefix("pr-") if tag in pr_tags else ""}
                   for tag in tags if image_exists(f"{repository}:{tag}")]
    specifications = [{"directory": str(path), "specification": path.name}
                      for path in sorted(Path("specifications").glob("*"))
                      if path.is_dir() and not path.name.startswith(".")]
    if not specifications:
        raise ValueError("No specification directories found")
    builds = [{**target, **specification, "id": str(index)}
              for target in targets for index, specification in enumerate(specifications)]
    if len(builds) > 256:
        raise ValueError("Build matrix exceeds GitHub's 256-job limit")
    comments = [target for target in targets if target["pr_number"]]
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write("builds=" + json.dumps({"include": builds}) + "\n")
        output.write("tags=" + json.dumps({"include": targets}) + "\n")
        output.write("has_builds=" + json.dumps(bool(builds)) + "\n")
        output.write("comments=" + json.dumps({"include": comments}) + "\n")
        output.write("has_comments=" + json.dumps(bool(comments)) + "\n")


if __name__ == "__main__":
    main()
