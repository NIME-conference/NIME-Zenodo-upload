"""Pure functions: bib entry -> Zenodo metadata, author names, token scrubbing,
DOI file parsing and token loading."""

import socket

import pytest
import requests

import nime_zenodo_upload.__main__ as zu

from conftest import parse_bib


def test_module_imports_without_secrets_file(tmp_path, monkeypatch):
    """Importing the module must not need secrets.toml (it used to read it at import)."""
    monkeypatch.chdir(tmp_path)
    import importlib
    importlib.reload(zu)
    assert 'upload' in zu.cli.commands and 'check' in zu.cli.commands


def test_entry_to_metadata_full_entry(bibdata):
    entry = bibdata.entries['NIME06_Baalman']
    data = zu.entry_to_metadata(entry, '2006-06-04', '4 June - 8 June, 2006')
    md = data['metadata']

    assert md['title'] == 'Test Installation'
    assert md['upload_type'] == 'publication'
    assert md['publication_type'] == 'conferencepaper'
    assert md['description'] == 'An installation.'
    assert md['conference_title'] == zu.CONFERENCE_TITLE
    assert md['conference_acronym'] == 'NIME'
    assert md['conference_dates'] == '4 June - 8 June, 2006'
    assert md['conference_place'] == 'Paris, France'
    assert md['conference_url'] == 'https://nime.org'
    assert md['publication_date'] == '2006-06-04'
    assert md['partof_title'] == md['imprint_title'] == (
        'Proceedings of the International Conference on New Interfaces for Musical Expression'
    )
    assert md['partof_pages'] == '1--2'
    assert md['imprint_isbn'] == '978-2-84426-314-8'
    assert md['imprint_issn'] == '2220-4806'
    assert md['communities'] == [{'identifier': 'nime_conference'}]
    assert md['conference_session'] == 'Installations'
    assert [c['name'] for c in md['creators']] == [
        'Baalman, Marije A.J.',
        'jasch',
        'dj sniff',
        'von Schlippenbach, Alexander',
        'Álvarez, José',
    ]


def test_related_identifier_for_issn_has_no_resource_type(bibdata):
    """Zenodo rejects resource_type 'journal-issn' with a 400 (issue #6)."""
    entry = bibdata.entries['NIME06_Baalman']
    md = zu.entry_to_metadata(entry, '2006-06-04', 'dates')['metadata']
    assert md['related_identifiers'] == [{'identifier': '2220-4806', 'relation': 'isPartOf'}]
    assert 'resource_type' not in md['related_identifiers'][0]


def test_minimal_entry_defaults(bibdata):
    entry = bibdata.entries['NIME06_Music']
    md = zu.entry_to_metadata(entry, '2006-06-04', 'dates')['metadata']
    assert md['description'] == '---'
    assert 'conference_session' not in md
    assert 'partof_pages' not in md
    assert 'related_identifiers' not in md
    assert md['imprint_isbn'] is None and md['imprint_issn'] is None
    assert md['creators'] == [{'name': 'Adachi, Tomomi'}]


def test_entry_without_title_raises_key_error():
    bib = parse_bib('@inproceedings{x, author={A, B}, url={https://nime.org/p/2006/x.pdf}}')
    with pytest.raises(KeyError):
        zu.entry_to_metadata(bib.entries['x'], '2006-06-04', 'dates')


def test_pdf_name_for(bibdata):
    assert zu.pdf_name_for(bibdata.entries['NIME06_Music']) == 'nime2006_music_Adachi.pdf'
    bib = parse_bib('@inproceedings{x, author={A, B}, title={T}}')
    with pytest.raises(KeyError):
        zu.pdf_name_for(bib.entries['x'])


@pytest.mark.parametrize('bib_author, expected', [
    ('{jasch}', 'jasch'),
    ('{dj sniff}', 'dj sniff'),
    ('Alexander von Schlippenbach', 'von Schlippenbach, Alexander'),
    ('van der Berg, Jan', 'van der Berg, Jan'),
    ('Álvarez, José', 'Álvarez, José'),
    ('Jørgensen, Søren Müller', 'Jørgensen, Søren Müller'),
    ('{Ensemble {Les Furies}}', 'Ensemble Les Furies'),
])
def test_author_name(bib_author, expected):
    bib = parse_bib(f'@inproceedings{{x, author={{{bib_author}}}, title={{T}}}}')
    person = bib.entries['x'].persons['Author'][0]
    assert zu.author_name(person) == expected


def test_latex_accents_are_not_converted():
    """The README asks for UTF-8 in the .bib file. LaTeX accents are not
    translated: the escaped umlaut is dropped and other accents keep their
    backslash, so `check --authors` shows them as a visible problem to fix."""
    bib = parse_bib(r'@inproceedings{x, author={Schm{\"o}ller, Ren{\'e}}, title={T}}')
    person = bib.entries['x'].persons['Author'][0]
    assert zu.author_name(person) == r"Schmoller, Ren\'e"


def test_scrub_removes_token_from_message():
    msg = "GET https://sandbox.zenodo.org/api/x?access_token=abc123&foo=1 failed (access_token=abc123)"
    scrubbed = zu._scrub(msg)
    assert 'abc123' not in scrubbed
    assert 'access_token=***' in scrubbed


def test_scrub_removes_token_from_real_requests_exception():
    """requests puts the full URL, query string included, in its exception text."""
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
    # Nothing listens on `port` now, so the connection is refused.
    with pytest.raises(requests.RequestException) as excinfo:
        requests.get(f'http://127.0.0.1:{port}/api/deposit/depositions',
                     params={'access_token': 'SECRET-TOKEN-XYZ'}, timeout=2)
    raw = str(excinfo.value)
    assert 'SECRET-TOKEN-XYZ' in raw, "test precondition: the raw exception quotes the token"
    assert 'SECRET-TOKEN-XYZ' not in zu._scrub(excinfo.value)


def test_recorded_pdfs_round_trip(tmp_path):
    doi_file = tmp_path / 'nime_dois.txt'
    doi_file.write_text(
        'Uploaded 2026-10-16 12:06 \n'
        'a.pdf,1,10.5072/zenodo.1\n'
        'b.pdf,2,10.5072/zenodo.2*b_file01.mp4;b_file02.mov,Some Title, with a comma\n'
    )
    assert zu.recorded_pdfs(doi_file) == {'a.pdf', 'b.pdf'}


def test_recorded_pdfs_missing_file(tmp_path):
    assert zu.recorded_pdfs(tmp_path / 'nope.txt') == set()


def test_doi_filename_and_url():
    assert zu.doi_filename(True) == 'nime_dois.txt'
    assert zu.doi_filename(False) == 'nime_dois_sandbox.txt'
    assert zu.zenodo_url(True) == 'https://zenodo.org'
    assert zu.zenodo_url(False) == 'https://sandbox.zenodo.org'


class TestLoadToken:
    def test_env_var_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv('ZENODO_SANDBOX_TOKEN', 'env-sandbox')
        monkeypatch.setenv('ZENODO_PUBLIC_TOKEN', 'env-public')
        secrets = tmp_path / 'secrets.toml'
        secrets.write_text("PUBLIC_TOKEN = 'file-public'\nSANDBOX_TOKEN = 'file-sandbox'\n")
        assert zu.load_token(False, secrets_file=secrets) == 'env-sandbox'
        assert zu.load_token(True, secrets_file=secrets) == 'env-public'

    def test_secrets_file_fallback(self, no_token_env, tmp_path):
        secrets = tmp_path / 'secrets.toml'
        secrets.write_text("PUBLIC_TOKEN = 'file-public'\nSANDBOX_TOKEN = 'file-sandbox'\n")
        assert zu.load_token(False, secrets_file=secrets) == 'file-sandbox'
        assert zu.load_token(True, secrets_file=secrets) == 'file-public'

    def test_missing_everything(self, no_token_env, tmp_path):
        with pytest.raises(zu.UploadError, match='ZENODO_SANDBOX_TOKEN'):
            zu.load_token(False, secrets_file=tmp_path / 'secrets.toml')

    def test_missing_key(self, no_token_env, tmp_path):
        secrets = tmp_path / 'secrets.toml'
        secrets.write_text("SANDBOX_TOKEN = 'file-sandbox'\n")
        with pytest.raises(zu.UploadError, match='PUBLIC_TOKEN'):
            zu.load_token(True, secrets_file=secrets)
