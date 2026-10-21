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
from packaging.version import Version, InvalidVersion

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs'
FORUM = 'https://discourse.stashapp.cc/t/list-of-plugin-sources/122'
OFFICIAL = 'https://stashapp.github.io/CommunityScripts/stable/index.yml'
PRIORITY_SOURCES = [
    'https://yinzburghbear.github.io/solid-guacamole/main/index.yml',
    OFFICIAL,
]
# Per-plugin overrides apply only after the priority repositories.
PREFERRED_SOURCES = {
    'stashBatchSave': 'https://dogmadragon.github.io/7dJx1qP-stash-plugins/main/index.yml',
}
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'StashUnifiedRepository/1.3 (+GitHub Actions)'})
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
    excluded_file = ROOT / 'excluded_sources.txt'

    excluded = set()

    if excluded_file.exists():
        excluded = {
            line.strip()
            for line in excluded_file.read_text(
                encoding='utf-8'
            ).splitlines()
            if line.strip() and not line.strip().startswith('#')
        }

    return sorted(discovered - excluded)


def source_priority(package_id, url):
    """Own repository, official stable, explicit third-party picks, then others."""
    if url in PRIORITY_SOURCES:
        return (0, PRIORITY_SOURCES.index(url))
    if url == PREFERRED_SOURCES.get(package_id):
        return (1, 0)
    return (2, 0)


def parsed_version(package):
    """Return a comparable version or None for nonstandard/missing versions."""
    raw = package.get('version')
    if raw is None:
        return None
    try:
        return Version(str(raw).strip())
    except InvalidVersion:
        return None


def choose_candidate(package_id, candidates):
    """Priorities first; highest comparable version within same tier."""
    def key(candidate):
        package, url = candidate
        return source_priority(package_id, url)

    best_tier = min(key(candidate) for candidate in candidates)
    eligible = [candidate for candidate in candidates if key(candidate) == best_tier]
    valid = [candidate for candidate in eligible if parsed_version(candidate[0]) is not None]
    if valid:
        newest = max(parsed_version(package) for package, _ in valid)
        tied = [candidate for candidate in valid if parsed_version(candidate[0]) == newest]
        winner = min(tied, key=lambda candidate: candidate[1])
        reason = 'highest_version' if len(eligible) > 1 and len(tied) < len(eligible) else 'source_order_tiebreak'
    else:
        winner = min(eligible, key=lambda candidate: candidate[1])
        reason = 'source_order_tiebreak'
    if len(eligible) == 1 and len(candidates) > 1:
        reason = 'source_priority' if best_tier[0] == 0 else 'preferred_source' if best_tier[0] == 1 else 'source_priority'
    return winner, reason


def main():
    OUT.mkdir(exist_ok=True)
    old_path = OUT / 'index.yml'
    old = {}
    if old_path.exists():
        try:
            old = {str(p['id']): p for p in yaml.safe_load(old_path.read_text(encoding='utf-8')) or [] if isinstance(p, dict) and p.get('id')}
        except Exception as exc:
            logging.warning('Old catalog invalid: %s', exc)
    candidates = {}
    selected = {}
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
                candidates.setdefault(package_id, []).append((package, url))
        except Exception as exc:
            logging.warning('Failed %s: %s', url, exc)
            failed.append({'url': url, 'error': str(exc)})
    if working == 0:
        raise RuntimeError('No upstream sources could be fetched; keeping previous catalog')
    for package_id, options in candidates.items():
        (winner, kept_url), reason = choose_candidate(package_id, options)
        selected[package_id] = winner
        for package, url in options:
            if package is winner:
                continue
            if package == winner and url == kept_url:
                continue
            conflicts.append({
                'id': package_id,
                'kept': kept_url,
                'kept_version': str(winner.get('version', '')),
                'skipped': url,
                'skipped_version': str(package.get('version', '')),
                'selection_reason': reason if source_priority(package_id, kept_url) == source_priority(package_id, url) else 'source_priority',
            })
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
