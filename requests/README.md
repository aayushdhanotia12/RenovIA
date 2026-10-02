# Requests for the live-model workflows

Push a change to `remodel.json` and `.github/workflows/remodel.yml` runs it: photos are
downloaded (URLs) or read from the repo, SAM 3 finds the surfaces, Claude picks Kober
finishes for each style, and the renders plus a contact sheet land in `runs/<run_id>/`.

Copy `remodel.example.json` to `remodel.json`, list the photos (paths in the repo, or image URLs), and push. The
workflow needs the repository secrets `ANTHROPIC_API_KEY` and `FAL_KEY`.
