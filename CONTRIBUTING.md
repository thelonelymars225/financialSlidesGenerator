# Contributing

## Branches

1. Start from `dev`.
2. Create a small branch such as `feature/source-extraction`.
3. Keep contracts and their consumers in the same pull request.
4. Run `pnpm check` and `pnpm test` before requesting review.
5. Merge approved release changes from `dev` into `main`.

## Repository rules

- Keep analysis contracts independent of PowerPoint, HTML, and any model vendor.
- Put deterministic calculations in code and retain formula provenance.
- Treat uploaded content as untrusted and never include it in ordinary logs.
- Use bounded repair attempts; do not add open-ended model retry loops.
- Add safe golden fixtures when changing extraction, analysis, or rendering.
- Record material stack decisions in `docs/decisions.md` before coupling code to
  a model, renderer, database, billing provider, or hosting platform.

## Data safety

Only synthetic, licensed, anonymized, or explicitly opted-in test data belongs in
this repository. Customer inputs and generated artifacts must remain outside Git.
