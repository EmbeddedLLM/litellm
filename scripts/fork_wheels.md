# Fork wheels

The fork carries the Anthropic streaming usage correction on upstream LiteLLM 1.106.0. Its regression covers zero reasoning counts, the text/media split, the estimate cap and preservation of provider-reported detail. The proxy reasoning serializer regression passes with upstream code, so the previous proxy workaround is unnecessary

Ordinary function tools bypass the optional MCP gateway imports. MCP tools retain the upstream gateway dispatch

The release preserves upstream's native extension and platform tags. OCR and Bedrock transcription require that extension, so a universal Python wheel would omit supported functionality

Build from a committed revision with an isolated environment:

```sh
uv run --no-project --with wheel==0.46.3 --with pydantic==2.12.5 python scripts/build_fork_wheels.py --revision HEAD
```

Use `--platform manylinux_2_28_x86_64` for a host-only build. The default builds all seven upstream platforms, including both musl variants

`scripts/fork_wheel_sources.json` pins the official PyPI URLs, SHA-256 hashes and upstream source revision. The builder verifies each download and checks that its original Python modules matches the pinned upstream commit. Windows wheel CRLF line endings are normalized only for that source comparison. It substitutes the corrected modules from the selected Git revision, then uses `wheel unpack` and `wheel pack` to regenerate `RECORD`

The builder rejects any change to files other than the corrected Python modules and `RECORD`. Native binaries, metadata and all remaining Python files remain byte-identical to the official wheel. `dist/fork/provenance.json` records the exact source commit, upstream inputs, packaging-tool version and output hashes. Archive timestamps derive from the source commit for reproducibility

Install and test the matching host wheel before publishing. Validation of the other archives' contents does not establish execution on their target platforms
