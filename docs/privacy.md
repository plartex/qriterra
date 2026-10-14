# Review data and diagnostic reports

Project snapshots honor Git's inventory and ignore rules. If Git fails inside a
repository, evaluation stops before sending source rather than walking files
without the repository's exclusions. Outside Git, nested `.gitignore` files are
processed with Git-style matching; unreadable rules stop the evaluation.
Symlinks, credential/secret files, environment files, diagnostic report names,
and runtime directories are excluded independently of Git tracking.

These exclusions bound the embedded snapshot. They are not a filesystem sandbox:
the selected harness must enforce its own tool permissions. Arbitrarily named
files and secrets embedded in ordinary source cannot be reliably identified.
Review the source you authorize the provider to inspect.

External exception text is not copied into evaluation errors. Reports retain
the exception type and fixed recovery categories. Debug output omits session
identifiers and arbitrary provider metadata, preserving numeric usage counters.

Normal reports retain target paths and source evidence for local investigation.
For a reduced JSON export use:

```console
qriterra evaluate file examples/sample_target.py --shareable --output review.json
```

The Python equivalent is `report.to_json(shareable=True)`. This removes the run
identifier and debug trace and masks target/local paths, UUIDs, known credential
formats and current secret environment values. It does not prove a report safe
to publish: source excerpts can contain business data or unknown secret formats.
Review exported evidence before sharing. Store local reports under `.runtime/`
or `debug-runs/`, which this repository excludes from Git.
