# nime-zenodo-upload

This Python project is for uploading NIME proceedings to Zenodo for archiving submissions and generating DOIs.

> **DANGER!** Uploading and publishing to Zenodo should only happen ONCE for each proceedings entry. You **must** test the script using Zenodo's sandbox multiple times and make super sure that your metadata records (`.bib` file) are absolutely correct before uploading to production Zenodo.

The python script reads a `.bib file` as used for the [NIME archive](https://github.com/NIME-conference/NIME-bibliography) and creates a deposition record on the [Zenodo website](https://zenodo.org/communities/nime_conference/).

The metadata from the .bib entries are tied to the article (.pdf file) and are published to Zenodo resulting in the creation of a DOI.

When this script is used to upload a new batch of papers the DOI and file name of each paper are added to the text file `nime_dois.txt`. Optionally (with the `--title` flag) the paper title is also appended as a final field on each line, which is especially handy when working with translated papers and multiple DOIs.

This project uses [Poetry](https://python-poetry.org) to manage dependencies.

For the proceedings chair of the conference, your workflow should be:

1. (before the conference) make sure **all** camera-ready submissions for each track are correct and hassle authors to update if there are errors—do this before the conference and emphasise that submissions cannot be updated after the conference.
2. (after the conference) create an accurate spreadsheet for all submissions that should be in the proceedings for each track. Create a `.bib` file from these data following the format in the [NIME bibliography](https://github.com/NIME-conference/NIME-bibliography). All fields must be filled in except for `doi`.
3. put the `.bib` file and pdf submission files into the `upload` directory of this project.
4. follow the "Install" and "Run" instructions below and test multiple times with the Zenodo sandbox to make sure that your metadata is correct and working.
5. upload to production Zenodo. The output file `nime_dois.txt` will show the DOI for each pdf you have uploaded.

Then you can pass the `nime_dois.txt` file to the proceedings officer of NIME who will:

6. use the data from `nime_dois.txt` to make a `.csv` file associating each bibtex item key with the DOI (and, if useful, the title).
7. use the `nime_bib` program in the [bibliography repo](https://github.com/NIME-conference/NIME-bibliography) to add DOIs to the correct bib file using the `csv` created in step 6.
8. use the `get_publications` script on the NIME website repo and deploy the website to update with DOIs.

## Install

You can install the project by running:

```bash
poetry install
```

## Run

You can test run the program by running:

```bash
poetry run python nime_zenodo_upload --help
```

To run the program you will need to:

- place all pdfs to be uploaded into the `upload` directory
- find your bibtex file (e.g., `nime2036_music.bib`) with metadata for the PDFs
- place a file named `secrets.toml` in the same directory as this readme file. The `secrets.toml` file should have two records:

  ```toml
  PUBLIC_TOKEN = 'replace-with-your-zenodo-public-token'
  SANDBOX_TOKEN = 'replace-with-your-zenodo-sandbox-token'
  ```

Once you have your data in place, you can view the metadata that will be created (without uploading) by running:

```bash
poetry run python nime_zenodo_upload check upload/nime2036_music.bib
```

It's a good idea to check the author names carefully as they may have been processed incorrectly:

```bash
poetry run python nime_zenodo_upload check upload/nime2036_music.bib --authors
```

Typically you would run the checks many times to make sure the metadata is perfect.

When your metadata is ready you can try uploading to the sandbox server:

```bash
poetry run python nime_zenodo_upload upload upload/nime2023_music.bib
```

By default, the program uploads to the Zenodo sandbox. When you are **absolutely ready to commit to the production server** you can run:

```bash
poetry run python nime_zenodo_upload upload upload/nime2023_music.bib --production
```

to do your final uploads.

You can also request that the title be written into `nime_dois.txt` alongside the DOI by adding the `--title` flag:

```bash
poetry run python nime_zenodo_upload upload upload/nime2023_music.bib --title
```

This is particularly useful when you later need to associate DOIs with translated titles or multiple language versions.

### Format of `nime_dois.txt`

After a run, the script appends lines to `nime_dois.txt` with one of two formats, depending on whether `--title` was used:

- **Default (no `--title`)**:

  ```text
  pdf_filename,zenodo_deposition_id,doi_or_marked_doi
  ```

- **With `--title`**:

  ```text
  pdf_filename,zenodo_deposition_id,doi_or_marked_doi,title
  ```

For example, with `--title`:

```text
nime2025_10.pdf,123456,10.5281/zenodo.15699550,Weaving Before Electronics: A Spiral Design Process for Sound-Interface Making
```

If **one or more supplementary files were skipped** because they were too large (see below), the DOI field is marked with `*` followed by a `;`‑separated list of the skipped filenames, e.g.:

```text
nime2025_10.pdf,123456,10.5281/zenodo.15699550*nime2025_10_file01.mp4;nime2025_10_file02.mov,Weaving Before Electronics: A Spiral Design Process for Sound-Interface Making
```

This allows you to identify which depositions need manual supplementary uploads while still keeping the title as a separate field at the end of each line (when `--title` is used).

During post-processing, you can:

- Without `--title`, treat the fields as:
  - `pdf_filename`
  - `zenodo_deposition_id`
  - `doi_or_marked_doi`
- With `--title`, treat the fields as:
  - `pdf_filename`
  - `zenodo_deposition_id`
  - `doi_or_marked_doi`
  - `title`

In both cases, if the DOI field contains `*`, split at the `*` to get:

- the actual DOI (before `*`), and  
- the list of supplementary filenames that need manual handling (after `*`, split by `;`).

The `--title` option is especially handy when working with translated papers, because we can add also the translated title to the bibtex (useful only for displaying the translated papers on nime.org).

## Conference Metadata

Some of the conference metadata is still hardcoded in the file, look inside `nime_zenodo_upload/__main__.py` and update the lines:

```python
PUBLICATION_DATE = '2023-05-31'
CONFERENCE_DATES = '31 May - 3 June, 2023'
CONFERENCE_TITLE = 'International Conference on New Interfaces for Musical Expression'
CONFERENCE_ACRONYM = 'NIME'
```

as needed for your edition.

## Additional files

### Naming convention

If a resource contains supplementary files that should be uploaded together with the paper, each supplementary file should have the same base file name as the paper PDF with an additional suffix such as `_file01`, `_file02`, etc., appended **before** the extension. For example:

```text
nime2025_10.pdf
nime2025_10_file01.mp4
nime2025_10_file02.mov
```

The script automatically searches the `upload` directory for files that share the base name plus an underscore, i.e. `nime2025_10_…`, and attempts to upload those as supplementary files for the corresponding deposition. Zenodo displays files alphabetically in its UI.

### Handling of large supplementary files (≥ 100 MB)

Zenodo (and/or the reverse proxy in front of it) imposes a maximum HTTP request body size. In practice, uploads larger than about 100 MB to both the sandbox and production endpoints result in an HTTP `413 Request Entity Too Large` response from nginx **before** the request reaches the Zenodo application.

To avoid failed uploads and crashes, this script handles large supplementary files as follows:

- Before uploading a supplementary file, it checks its size on disk.
- If a supplementary file is **larger than 100 MB**:
  - The script **does not attempt to upload it**.
  - A warning is printed to the console indicating that the file was skipped and must be uploaded manually via the Zenodo web UI.
  - The filename is recorded so that it can be associated with the corresponding DOI in `nime_dois.txt`.

- If the script does attempt an upload (for files ≤ 100 MB) and Zenodo still returns an error (including HTTP `413`), the script:
  - Prints the HTTP status and error body (handling both JSON and HTML responses),
  - Marks that supplementary file as skipped,
  - Continues with the rest of the files and the deposition instead of aborting the whole run.

### Marking DOIs for entries with skipped supplementary files

When any supplementary files are skipped for a given paper (either because they are larger than 100 MB or because the server rejected them), the corresponding DOI entry in `nime_dois.txt` is marked:

- The DOI is followed by `*` and then a `;`‑separated list of the skipped filenames.

Example (with `--title`):

```text
nime2025_10.pdf,123456,10.5281/zenodo.15699550*nime2025_10_file01.mp4,Weaving Before Electronics: A Spiral Design Process for Sound-Interface Making
nime2025_14.pdf,123457,10.5281/zenodo.15699591*nime2025_14_file01.mp4;nime2025_14_file02.mov,Another Example Title
nime2025_17.pdf,123458,10.5281/zenodo.15699598,Yet Another Title
```

- `nime2025_10.pdf` has one skipped supplementary file (`nime2025_10_file01.mp4`).
- `nime2025_14.pdf` has two skipped supplementary files.
- `nime2025_17.pdf` had no problems; its DOI is unmarked.
- In all cases, the final field is the paper title (when `--title` was used).

During post-processing, you can:

1. Parse each line of `nime_dois.txt`.
2. Split the DOI field on `*` (if present) to separate the pure DOI from the list of skipped filenames.
3. Manually upload those large supplementary files to the corresponding Zenodo deposition via the web UI.
4. Optionally, update or regenerate `nime_dois.txt` once the manual uploads are complete and you know the final DOIs you want to distribute.

## The `.bib` file

The .bib file: Special characters in the .bib file should be written with UTF-8 symbols and **not** in LaTeX code. This follows the convention for the bibliography repo.

## Acknowledgements

- Thanks to [Benedikte Wallace](https://www.linkedin.com/in/benedikte-wallace-8b489782/) for developing the Zenodo upload script in 2017–2018 or so.
- Charles Martin did some work on this in 2024.
- Stefano Fasciani did some work on this in 2025 and 2026.