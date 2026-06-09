########################################################
'''
Written by Benedikte Wallace, 2018, edited by Charles Martin, 2024, and Stefano Fasciani 2025-2026.

This script reads .bib files in NIME archive and creates a deposition record
on the Zenodo website. The metadata from the .bib entries are tied to the
article (.pdf file) and are published to Zenodo resulting in the creation
of a DOI. When this script is used to upload a new batch of papers the DOI
and file name of each paper are added to the text file nime_dois.txt.

Supplementary files:

If a resource contains supplementary files that should be uploaded together with the paper, each
supplementary file should have the same base file name as the paper PDF with an additional
suffix such as _file01, _file02, etc., appended before the extension, e.g.:

    nime2025_10.pdf
    nime2025_10_file01.mp4
    nime2025_10_file02.mov

Supplementary files larger than 100 MB are skipped by this script: they are NOT uploaded via
the API. The script:
  - prints a warning for each skipped file,
  - marks the corresponding DOI line in nime_dois.txt by appending "*" followed by a ";"-separated
    list of skipped filenames, so they can be uploaded manually via the Zenodo web UI.

Zenodo displays files alphabetically in its UI.
'''
########################################################


import json
import requests
import datetime
#import latexcodec # TODO: remove this.
import click
import os
import tomllib
import pprint

from pybtex.database.input import bibtex

# Bibtex parser
parser = bibtex.Parser()

UPLOAD_FOLDER = './upload/'
PUBLICATION_DATE = '2025-06-19'
CONFERENCE_DATES = '24 June - 27 June, 2025'
CONFERENCE_TITLE = 'International Conference on New Interfaces for Musical Expression'
CONFERENCE_ACRONYM = 'NIME'

# Maximum size for automatic supplementary upload (100 MB)
MAX_SUPP_BYTES = 100 * 1024 * 1024
# Maximum size for PDF upload (100 MB) – PDFs over this limit will abort the whole run.
MAX_PDF_BYTES = 100 * 1024 * 1024

# New dois and file names are appended to the text file nime_dois.txt
DOI_FILENAME = "nime_dois.txt"
# Add date and time for this upload
with open(DOI_FILENAME, 'a') as doi_file:
    doi_file.write(datetime.datetime.now().strftime("Uploaded %Y-%m-%d %H:%M \n"))

# Tokens, replace with public and sandbox tokens from Zenodo:
with open("secrets.toml", "rb") as f:
    secret_data = tomllib.load(f)


def _print_response_json_or_text(resp, color='red'):
    """Helper to print a requests.Response as JSON if possible, otherwise as raw text."""
    try:
        data = resp.json()
        click.secho(data, fg=color)
    except ValueError:
        # Not JSON (e.g., HTML 413 page); print raw text
        click.secho(resp.text, fg=color)


def upload_to_zenodo(metadata, pdf_path, production_zenodo=False):
    '''
    upload(metadata, pdf_path):
    - connects to zenodo REST API,
    - creates a new record,
    - enters metadata,
    - uploads the .pdf and supplementary files
    - publishes it
    '''

    if production_zenodo:
        ZENODO_URL = 'https://zenodo.org'
        TOKEN = secret_data['PUBLIC_TOKEN']  # either SANDBOX_TOKEN or PUBLIC_TOKEN
    else:
        ZENODO_URL = 'https://sandbox.zenodo.org'
        TOKEN = secret_data['SANDBOX_TOKEN']

    # Track supplementary files that were too large or otherwise skipped
    skipped_supplementary = []

    click.secho(f"Starting new upload for: {pdf_path} to {ZENODO_URL}", fg='yellow')
    url = ZENODO_URL + '/api/deposit/depositions'
    access_depositions = requests.get(url, params={'access_token': TOKEN})
    click.secho(f"Access depositions: {access_depositions.status_code}", fg='yellow')

    # Create new paper submission - add parsed metadata
    headers = {"Content-Type": "application/json"}
    new_deposition = requests.post(
        url,
        params={'access_token': TOKEN},
        json=metadata,
        headers=headers
    )

    # If creation of new deposition is unsuccessful, abort
    if new_deposition.status_code > 210:
        click.secho(
            f"Error happened during submission {pdf_path}, status code: "
            f"{new_deposition.status_code}",
            fg='red'
        )
        _print_response_json_or_text(new_deposition, color='red')
        return

    submission_id = json.loads(new_deposition.text)["id"]

    # Upload the pdf file
    url_files = (
        ZENODO_URL +
        "/api/deposit/depositions/{id}/files?access_token={token}".format(
            id=str(submission_id),
            token=TOKEN
        )
    )
    upload_metadata = {'filename': pdf_path}
    pdf_full_path = os.path.join(UPLOAD_FOLDER, pdf_path)
    with open(pdf_full_path, 'rb') as pdf_file:
        add_file = requests.post(url_files, data=upload_metadata, files={'file': pdf_file})

    # If upload of file is unsuccessful, abort
    if add_file.status_code > 210:
        click.secho(
            f"Error happened during file upload of {pdf_path}, status code: "
            f"{add_file.status_code}",
            fg='red'
        )
        _print_response_json_or_text(add_file, color='red')
        return

    # Upload supplementary files (if any)
    all_files = os.listdir(UPLOAD_FOLDER)
    pdf_fname_prefix = pdf_path[:-4] + "_"
    matching_files = [file for file in all_files if file.startswith(pdf_fname_prefix)]

    for extra_file_path in matching_files:
        if extra_file_path == pdf_path:
            continue

        full_extra_path = os.path.join(UPLOAD_FOLDER, extra_file_path)
        file_size = os.path.getsize(full_extra_path)

        # Pre-check size: skip if over MAX_SUPP_BYTES
        if file_size > MAX_SUPP_BYTES:
            click.secho(
                f"Skipping supplementary file {extra_file_path} "
                f"({file_size / (1024 * 1024):.1f} MB) – above automatic upload limit "
                f"({MAX_SUPP_BYTES / (1024 * 1024):.0f} MB).",
                fg='yellow'
            )
            click.secho(
                "Upload this file manually via the Zenodo web UI and attach it to the deposition.",
                fg='yellow'
            )
            skipped_supplementary.append(extra_file_path)
            continue

        click.secho(
            f"Starting upload for supplementary file: {extra_file_path} to {ZENODO_URL}",
            fg='yellow'
        )
        upload_metadata = {'filename': extra_file_path}
        with open(full_extra_path, 'rb') as extra_file:
            add_file = requests.post(url_files, data=upload_metadata, files={'file': extra_file})

        # If upload of file is unsuccessful, warn and continue
        if add_file.status_code > 210:
            click.secho(
                f"Error happened during supplementary file upload of {extra_file_path}, "
                f"status code: {add_file.status_code}",
                fg='red'
            )

            if add_file.status_code == 413:
                click.secho(
                    "Server reports the file is too large (HTTP 413). "
                    "You must upload this file manually via the Zenodo web UI.",
                    fg='red'
                )

            _print_response_json_or_text(add_file, color='red')
            skipped_supplementary.append(extra_file_path)
            # Do not abort the whole deposition; continue with other files
            continue

    click.secho(f"{pdf_path} submitted with ID {submission_id}", fg='green')

    # publish the new deposition
    publish_record = requests.post(
        f"{ZENODO_URL}/api/deposit/depositions/{submission_id}/actions/publish",
        params={'access_token': TOKEN}
    )

    # If publish unsuccessful, abort
    if publish_record.status_code > 210:
        click.secho(
            f"Error happened during publish, status code: {publish_record.status_code}",
            fg='red'
        )
        _print_response_json_or_text(publish_record, color='red')
        return
    click.secho(f"{pdf_path} PUBLISHED with ID {submission_id}", fg='green')

    # get back the deposition to confirm the DOI
    retrieved_deposition = requests.get(
        f"{ZENODO_URL}/api/deposit/depositions/{submission_id}",
        params={'access_token': TOKEN}
    )
    retrieved_doi = retrieved_deposition.json()['doi']
    click.secho(f"{pdf_path} confirmed DOI is {retrieved_doi}", fg='green')

    # If any supplementary files were skipped, mark DOI and record filenames.
    # We use ';' as separator for multiple filenames so the line remains valid CSV.
    doi_field = retrieved_doi
    if skipped_supplementary:
        skipped_list = ';'.join(skipped_supplementary)
        doi_field = f"{retrieved_doi}*{skipped_list}"
        click.secho(
            f"Supplementary files skipped for {pdf_path}: {skipped_list}. "
            f"Marked DOI as {doi_field} in {DOI_FILENAME}.",
            fg='yellow'
        )

    # Record in the csv file.
    with open(DOI_FILENAME, 'a') as doi_file:
        doi_file.write(f'{pdf_path},{submission_id},{doi_field}\n')


def format_metadata(bibfilename, verbose=False, upload_pdf=False,
                    print_authors=False, production_zenodo=False):
    '''
    format_metadata(bibfilename):
    - formats contents of entries in the .bib file referenced by bibfilename
    - for each entry, metadata is formatted and the upload function
      above is called in order to publish record
    '''
    bibdata = parser.parse_file(bibfilename)

    # If we are going to upload PDFs, pre-check that none of them exceed MAX_PDF_BYTES.
    if upload_pdf:
        oversized_pdfs = []
        missing_pdfs = []
        for bib_id in bibdata.entries:
            b = bibdata.entries[bib_id].fields
            try:
                conf_url = b['Url']
                pdf_name = conf_url.rsplit('/', 1)[-1]
                pdf_path = os.path.join(UPLOAD_FOLDER, pdf_name)

                if not os.path.exists(pdf_path):
                    missing_pdfs.append(pdf_name)
                    continue

                size = os.path.getsize(pdf_path)
                if size > MAX_PDF_BYTES:
                    oversized_pdfs.append((pdf_name, size))
            except KeyError:
                # If Url is missing, this entry will fail later anyway; let the normal logic handle it.
                continue

        if missing_pdfs:
            click.secho(
                "The following PDFs referenced in the .bib file do not exist in the upload folder:",
                fg='red'
            )
            for name in sorted(set(missing_pdfs)):
                click.secho(f"  - {name}", fg='red')
            click.secho(
                "Fix the missing files before running the upload.",
                fg='red'
            )
            # Abort before any upload.
            return

        if oversized_pdfs:
            click.secho(
                "One or more PDFs are larger than 100 MB and will fail to upload:",
                fg='red'
            )
            for name, size in sorted(set(oversized_pdfs)):
                click.secho(
                    f"  - {name}: {size / (1024 * 1024):.1f} MB",
                    fg='red'
                )
            click.secho(
                "Zenodo rejects these large PDF uploads (HTTP 413). "
                "Please compress or split these PDFs to be under 100 MB and try again.",
                fg='red'
            )
            click.secho(
                "Aborting before starting any uploads. No Zenodo records were created.",
                fg='red'
            )
            return

    title = 'title'
    abstract = 'abstract'
    address = 'address'
    creators = 'creators'
    pubdate = '20XX-06-01'
    pages = 'x-x'
    conf_url = ''
    pdf_name = ''
    creators = []

    # loop through the individual entries
    for bib_id in bibdata.entries:
        title = 'title'
        abstract = 'abstract'
        address = 'address'
        creators = 'creators'
        pubdate = '20XX-06-01'
        pages = 'x-x'
        conf_url = ''
        pdf_name = ''
        creators = []

        b = bibdata.entries[bib_id].fields
        try:
            conf_url = b['Url']
            pdf_name = conf_url.rsplit('/', 1)[-1]

            if not os.path.exists(UPLOAD_FOLDER + pdf_name):
                click.secho(f'PDF: {pdf_name} does not exist in the upload folder!', fg='red')
                raise Exception(f'The PDF {pdf_name} did not exist in the upload folder.')

            title = b['Title']
            for author in bibdata.entries[bib_id].persons["Author"]:
                author_name = str(author)
                # TODO: would be better to use https://github.com/phfaist/pylatexenc
                # author_name = bytes(author_name,"utf-8").decode("latex","ignore")
                author_name = author_name.replace("}", "")
                author_name = author_name.replace("{", "")
                author_name = author_name.replace("\\\"", "")
                creators.append({'name': author_name})
                if print_authors:
                    pprint.pp(author_name)

            yr_seg = conf_url.rsplit('/', 1)[-2]
            yr = yr_seg.rsplit('/', 1)[-1]
            pubdate = yr + pubdate[4:]

            address = b.get('Address', 'Address')
            pages = b.get('Pages', None)
            abstract = b.get('Abstract', '---')  # if no abstract is found, --- will be used as default
            track = b.get('track')  # could be used for conference_session key
            partof_title = b.get('booktitle')
            conf_session = b.get('note', None)
            isbn = b.get('isbn')
            issn = b.get('issn')

            data = {
                'metadata': {
                    'title': title,
                    'upload_type': 'publication',
                    'publication_type': 'conferencepaper',
                    'description': abstract,
                    'conference_title': CONFERENCE_TITLE,
                    'conference_acronym': CONFERENCE_ACRONYM,
                    'conference_dates': CONFERENCE_DATES,  # hard coded, needs to be fixed
                    'conference_place': address,
                    'conference_url': 'https://nime.org',
                    'publication_date': PUBLICATION_DATE,  # pubdate, # TODO fix this aspect
                    'partof_title': partof_title,
                    'creators': creators,
                    'communities': [{'identifier': 'nime_conference'}],  # adds to Zenodo NIME community
                    'imprint_isbn': isbn,
                    'journal_issn': issn
                }
            }

            if conf_session is not None:
                data['metadata']['conference_session'] = conf_session

            if pages is not None:
                data['metadata']['partof_pages'] = pages

            if verbose:
                pprint.pp(data['metadata'])

            if upload_pdf:
                upload_to_zenodo(data, pdf_name, production_zenodo=production_zenodo)

        except (KeyError):
            # TODO Write failed bib ID's to a text file?
            print("KeyError! Entry did not contain fields needed, continuing to next id - failed bib id: ", bib_id)
            raise


@click.command()
@click.argument('bibfile', type=click.Path(exists=True))
@click.option('--production', is_flag=True)
def upload(bibfile, production):
    """Process metadata from a .bibtex file and upload to Zenodo."""
    if production:
        click.secho(
            "WARNING! You are uploading to the production Zenodo server! "
            "Make sure you are ready! Cancel if not!",
            fg="red"
        )
    else:
        click.secho(
            "You are uploading to the sandbox Zenodo server! Test here as much as you want.",
            fg="green"
        )
    input("Press Enter to continue or Ctrl-C to abort.")
    format_metadata(
        bibfile,
        upload_pdf=True,
        verbose=False,
        print_authors=False,
        production_zenodo=production
    )


@click.command()
@click.argument('bibfile', type=click.Path(exists=True))
@click.option('--authors', is_flag=True)
def check(bibfile, authors):
    """Process metadata from a .bibtex file and print out to check it."""
    if authors:
        format_metadata(
            bibfile,
            upload_pdf=False,
            verbose=False,
            print_authors=True,
            production_zenodo=False
        )
    else:
        format_metadata(
            bibfile,
            upload_pdf=False,
            verbose=True,
            print_authors=False,
            production_zenodo=False
        )


@click.group()
def cli():
    pass


if __name__ == '__main__':
    cli.add_command(upload)
    cli.add_command(check)
    cli()
