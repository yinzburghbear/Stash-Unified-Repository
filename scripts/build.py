#!/usr/bin/env python3
"""Build a unified Stash plugin index from community and custom source URLs."""
import json
import logging
import os
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs'
FORUM = 'https://discourse.stashapp.cc/t/list-of-plugin-sources/122'
OFFICIAL = 'https://stashapp.github.io/CommunityScripts/stable/index.yml'
PREFERRED_SOURCES = {
    'stashBatchSave': 'https://dogmadragon.github.io/7dJx1qP-stash-plugins/main/index.yml',
}
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'StashUnifiedRepository/1.0 (+GitHub Actions)'})
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')


def get(url):
    response = SESSION.get(url, timeout=25)
    response.raise_for_status()
    return response.text


def sanitize_yaml(value):
    """Remove Unicode control characters disallowed by YAML (including C1)."""
    cleaned = ''.join(
        ch for ch in value
        if ch in '\t\n\r' or (ord(ch) >= 0x20 and not 0x7F <= ord(ch) <= 0x9F)
    )
    return cleaned


def valid_url(url):
    parsed = urlparse(url)
    return parsed.scheme == 'https' and bool(parsed.netloc) and not parsed.username and not parsed.password


def sources():
    discovered = {OFFICIAL}
    try:
        soup = BeautifulSoup(get(FORUM), 'html.parser')
        for anchor in soup.select('a[href]'):
            url = anchor.get('href', '').strip()
            if valid_url(url) and (url.lower().split('?')[0].endswith(('.yml', '.yaml'))):
                discovered.add(url)
    except Exception as exc:
        logging.warning('Forum unavailable: %s', exc)
    for line in (ROOT / 'sources.txt').read_text(encoding='utf-8').splitlines():
        url = line.strip()
        if url and not url.startswith('#') and valid_url(url):
            discovered.add(url)
    # Reuse previously discovered URLs when the forum is temporarily unavailable.
    previous = OUT / 'sources.json'
    if previous.exists():
        try:
            discovered.update(u for u in json.loads(previous.read_text(encoding='utf-8')) if valid_url(u))
        except Exception as exc:
            logging.warning('Could not read previous source list: %s', exc)
    return sorted(discovered)


def main():
    OUT.mkdir(exist_ok=True)
    old_path = OUT / 'index.yml'
    old = {}
    if old_path.exists():
        try:
            old = {str(p['id']): p for p in yaml.safe_load(old_path.read_text(encoding='utf-8')) or [] if isinstance(p, dict) and p.get('id')}
        except Exception as exc:
            logging.warning('Old catalog invalid: %s', exc)
    selected = {}
    origin = {}
    failed = []
    conflicts = []
    working = 0
    all_sources = sources()
    for url in all_sources:
        try:
            raw = get(url)
            cleaned = sanitize_yaml(raw)
            if cleaned != raw:
                logging.warning('Sanitized invalid YAML control characters in %s', url)
            packages = yaml.safe_load(cleaned)
            if not isinstance(packages, list):
                raise ValueError('index is not a YAML list')
            working += 1
            for item in packages:
                if not isinstance(item, dict) or not item.get('id') or not item.get('path'):
                    continue
                package = dict(item)
                package_id = str(package['id'])
                package['path'] = urljoin(url, str(package['path']))
                if not valid_url(package['path']):
                    continue
                if package_id in selected:
                    if package != selected[package_id]:
                        preferred = PREFERRED_SOURCES.get(package_id)
                        if preferred == url and origin[package_id] != preferred:
                            conflicts.append({'id': package_id, 'kept': url, 'skipped': origin[package_id]})
                            selected[package_id] = package
                            origin[package_id] = url
                        else:
                            conflicts.append({'id': package_id, 'kept': origin[package_id], 'skipped': url})
                    continue
                selected[package_id] = package
                origin[package_id] = url
        except Exception as exc:
            logging.warning('Failed %s: %s', url, exc)
            failed.append({'url': url, 'error': str(exc)})
    if working == 0:
        raise RuntimeError('No upstream sources could be fetched; keeping previous catalog')
    # Retain previously published packages from sources currently offline.
    for package_id, package in old.items():
        if package_id not in selected:
            selected[package_id] = package
    merged = sorted(selected.values(), key=lambda p: (str(p.get('name', p['id'])).casefold(), str(p['id']).casefold()))
    if not merged:
        raise RuntimeError('Empty merged catalog; refusing to publish')
    (OUT / 'index.yml').write_text(yaml.safe_dump(merged, sort_keys=False, allow_unicode=True), encoding='utf-8')
    (OUT / 'sources.json').write_text(json.dumps(all_sources, indent=2) + '\n', encoding='utf-8')
    (OUT / 'report.json').write_text(json.dumps({'sources_total': len(all_sources), 'sources_working': working, 'packages': len(merged), 'failed': failed, 'conflicts': conflicts}, indent=2) + '\n', encoding='utf-8')
    logging.info('Published %s packages from %s/%s sources; %s conflicts', len(merged), working, len(all_sources), len(conflicts))


if __name__ == '__main__':
    main()
