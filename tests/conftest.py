"""Shared fixtures: a small .bib file, an upload folder with fake PDFs, and a
fake Zenodo server built with the `responses` library. No test touches the
network or needs a secrets file."""

import textwrap

import pytest
import responses
from pybtex.database.input import bibtex

import nime_zenodo_upload.__main__ as zu

SANDBOX = 'https://sandbox.zenodo.org'
DEPOSITIONS = f'{SANDBOX}/api/deposit/depositions'
TOKEN = 'sandbox-token-SECRET'

BIB = textwrap.dedent(r"""
    @inproceedings{NIME06_Baalman,
      author = {Baalman, Marije A.J. and {jasch} and {dj sniff} and Alexander von Schlippenbach and Álvarez, José},
      title = {Test Installation},
      pages = {1--2},
      booktitle = {Proceedings of the International Conference on New Interfaces for Musical Expression},
      address = {Paris, France},
      issn = {2220-4806},
      isbn = {978-2-84426-314-8},
      note = {Installations},
      track = {Installations},
      abstract = {An installation.},
      url = {https://www.nime.org/proceedings/2006/nime2006_installations_Baalman.pdf},
      year = {2006}
    }

    @inproceedings{NIME06_Music,
      author = {Adachi, Tomomi},
      title = {A Music Piece},
      booktitle = {Proceedings of the International Conference on New Interfaces for Musical Expression},
      address = {Paris, France},
      url = {https://www.nime.org/proceedings/2006/nime2006_music_Adachi.pdf},
      year = {2006}
    }
""")

PDFS = ['nime2006_installations_Baalman.pdf', 'nime2006_music_Adachi.pdf']


def parse_bib(text):
    return bibtex.Parser().parse_string(text)


@pytest.fixture
def bibdata():
    return parse_bib(BIB)


@pytest.fixture
def bibfile(tmp_path):
    path = tmp_path / 'test.bib'
    path.write_text(BIB, encoding='utf-8')
    return path


@pytest.fixture
def upload_folder(tmp_path):
    folder = tmp_path / 'upload'
    folder.mkdir()
    for name in PDFS:
        (folder / name).write_bytes(b'%PDF-1.4 fake\n')
    return folder


@pytest.fixture
def doi_file(tmp_path):
    return tmp_path / 'nime_dois_sandbox.txt'


@pytest.fixture
def no_waits(monkeypatch):
    """Make retries instant so tests of the failure paths stay fast."""
    monkeypatch.setattr(zu, 'RETRY_WAIT', 0)
    monkeypatch.setattr(zu.time, 'sleep', lambda s: None)


@pytest.fixture
def no_token_env(monkeypatch):
    monkeypatch.delenv('ZENODO_PUBLIC_TOKEN', raising=False)
    monkeypatch.delenv('ZENODO_SANDBOX_TOKEN', raising=False)


@pytest.fixture
def zenodo(no_waits):
    """A fake sandbox Zenodo. Any request to an unregistered URL raises
    ConnectionError, so a test fails if the code calls something unexpected."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


def add_happy_path(mock, deposition_id=123, doi='10.5072/zenodo.123', publish_status=202):
    """Register the create -> file -> publish -> confirm sequence."""
    mock.add(responses.GET, DEPOSITIONS, json=[], status=200)
    mock.add(responses.POST, DEPOSITIONS, json={'id': deposition_id}, status=201)
    mock.add(responses.POST, f'{DEPOSITIONS}/{deposition_id}/files', json={}, status=201)
    mock.add(
        responses.POST, f'{DEPOSITIONS}/{deposition_id}/actions/publish',
        json={}, status=publish_status
    )
    mock.add(
        responses.GET, f'{DEPOSITIONS}/{deposition_id}',
        json={'id': deposition_id, 'submitted': True, 'state': 'done', 'doi': doi}, status=200
    )


def calls_to(mock, method, path_suffix):
    return [c for c in mock.calls if c.request.method == method and c.request.path_url.split('?')[0].endswith(path_suffix)]
