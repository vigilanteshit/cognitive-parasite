# Preparing a public release

The working repository contains historical development material, including environment configuration, logs, notebook outputs, and private research data. Removing a file from the current checkout does not remove it from Git history. Treat the existing repository and its refs as private research material.

Before publishing, rotate credentials that have ever appeared in the repository or its history, then verify the replacement credentials are not present in any public material. Removing a key from Git does not invalidate the key. If the repository or any refs may already have been accessible to others, assume exposed credentials may have been copied.

Prepare `vigilanteshit/cognitive-parasite` from a reviewed export containing only intended source, documentation, and distributable assets. Keep the original private repository intact. Create the public repository history from the approved export as a clean root; do not publish the existing refs or tags, and do not force-push a rewritten version of the research history. Confirm the intended destination and reviewed export before publishing.

## Run the audit

The scanner uses only Python's standard library. It reports file path, rule, and (for history findings) Git object ID; it never prints matched text or source lines. History findings identify representative file paths and objects reachable from the repository's refs. A nonzero exit status means findings were reported or the audit could not complete.

From a Git checkout, scan tracked files:

```powershell
python scripts/audit_publication.py --root .
```

To inspect all files in a prepared export directory, including untracked files:

```powershell
python scripts/audit_publication.py --root path\to\public-export --export
```

After initializing the clean release repository and creating its intended public history, inspect the objects reachable from its refs:

```powershell
python scripts/audit_publication.py --root path\to\release-repository --history
```

The history option checks refs in the repository passed to it. Run it on the release repository, not on the private research checkout when preparing public material. The scanner is a review aid: inspect the export and audit findings before publication, and use a credential scanner appropriate to the hosting platform as an additional check.

## Publication details

The project uses the MIT License; the repository's `LICENSE` file is the authoritative license text. `CITATION.cff` identifies the software author by their GitHub handle and links to the public repository. Research papers that inform the design are attributed in [Research and design](research.md); citing a paper does not imply that its authors contributed to this software.
