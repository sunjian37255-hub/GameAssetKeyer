# Contributing to GameAssetKeyer

Contributions are welcome. For substantial behavior or dependency changes, open an issue first so the approach can be discussed.

By submitting a contribution to GameAssetKeyer, you agree that your contribution is provided under the Mozilla Public License 2.0 (MPL-2.0). No contributor license agreement is required.

1. Fork the repository.
2. Create a focused branch.
3. Make the smallest coherent change.
4. Run the checks below.
5. Open a pull request describing the change and its effect on output pixels.

```bat
python -m pip install -r requirements.txt
python GameAssetKeyer.py --check
python -m unittest discover -s tests -v
```

Please preserve deterministic offline operation, Alpha monotonicity, Pipeline invalidation, and Final Preview/Export consistency. Do not add AI model or runtime dependencies without prior discussion.

Do not include proprietary game assets, credentials, local project directories, build outputs, or generated runtime files in a contribution.
