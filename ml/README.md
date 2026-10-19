# ml: SilentBand host tools (`sb`)

```sh
uv sync && uv run pytest     # setup + tests
uv run sb --help
```

## Gaddy dataset (for `sb gaddy`)
Gaddy & Klein silent-speech EMG, CC-BY-4.0, https://zenodo.org/records/4064409 (3.7 GB). Not committed; ml/data is gitignored.

```sh
mkdir -p data && cd data
curl -L -o emg_data.tar.gz "https://zenodo.org/records/4064409/files/emg_data.tar.gz?download=1"
tar xzf emg_data.tar.gz      # -> ml/data/emg_data/
```

Your own recordings and models also live under ml/data/ (also gitignored).
