# Contributing

Thanks for building on World Builder!

## License of contributions — read this first

World Builder is dual-licensed: **GPL-3.0-or-later** for the community, plus **commercial licenses**
offered by the maintainer (see `LICENSE-COMMERCIAL.md`). For that model to remain legally possible,
every contribution must be usable through both channels.

**By submitting a contribution** (pull request, patch, or otherwise) **you agree that:**

1. your contribution is licensed under GPL-3.0-or-later, and
2. you grant Sairam (sairamvendra) a perpetual, worldwide, non-exclusive, royalty-free right to
   relicense your contribution under other terms, including commercial licenses.

You keep the copyright to your work. If you can't agree to this, open an issue to discuss your idea
instead of sending code.

## Practical notes

- One feature per PR; keep the single-file addon structure unless there's a strong reason not to.
- Target Blender 4.2+; the project runs on 5.x APIs with version guards (see the `media_type` and
  layered-actions handling for the pattern).
- Never commit `.env`, API keys, machine-specific paths, or generated files (`wb_exec.py`, `renders/`,
  `worlds/`, `steps/` are gitignored).
