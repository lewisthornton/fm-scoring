#!/usr/bin/env python3
"""Rangers FM27 autosave watcher with a *selective* SQLite player history.

Tracks your managed-club squad and the actual players in the latest filtered FM
View Exporter CSV. Unique ID is optional: name, age, club and attributes can be
used to match the rows. Never persists the full 50k+ player world.

fmsave must be installed and on PATH. FM View Exporter is an optional, independent
in-game plugin. F9 exports an in-game filtered list; there is no automatic FM
search-interest extraction from .fm files.

This program never writes to a Football Manager save. It copies the save to a
private temporary directory and parses only the copy.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from rangers_club import club_uid, rangers_names, rangers_ids

DEFAULT_DB = Path(__file__).resolve().parent / 'fm_rangers_scoped.sqlite3'
BASE_FIELDS = {
    'uid','unique_id','name','birth_date','age','club_uid','club_name',
    'team_id','team_slot','natural_positions','accomplished_positions',
    'left_foot','right_foot','ability_current','ability_potential',
    'transfer_value','transfer_value_state','contract_wage','contract_start',
    'contract_end','contract_squad_status','on_loan','loan_parent_club_uid',
    'loan_parent_club_name','loan_end','traits','traits_code',
}
FIELD_PREFIXES=('attributes_','positions_','personality_')
SCHEMA='''
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    career TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    selection_sha256 TEXT NOT NULL,
    game_date TEXT,
    game_build TEXT,
    imported_utc TEXT NOT NULL,
    player_count INTEGER NOT NULL,
    changed_count INTEGER NOT NULL,
    UNIQUE(career,source_sha256,selection_sha256)
);
CREATE INDEX IF NOT EXISTS ix_snapshots_career_date ON snapshots(career,game_date);
CREATE TABLE IF NOT EXISTS player_versions (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    career TEXT NOT NULL,
    player_key TEXT NOT NULL,
    player_uid TEXT NOT NULL,
    unique_id TEXT,
    name TEXT,
    club_uid TEXT,
    current_ability INTEGER,
    potential_ability INTEGER,
    wage INTEGER,
    record_hash TEXT NOT NULL,
    record_json TEXT NOT NULL,
    PRIMARY KEY(snapshot_id,player_key)
);
CREATE INDEX IF NOT EXISTS ix_versions_history ON player_versions(career,player_key,snapshot_id);
CREATE TABLE IF NOT EXISTS player_latest (
    career TEXT NOT NULL,
    player_key TEXT NOT NULL,
    record_hash TEXT NOT NULL,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    PRIMARY KEY(career,player_key)
);
CREATE TABLE IF NOT EXISTS cohort_membership (
    career TEXT NOT NULL,
    player_key TEXT NOT NULL,
    cohort TEXT NOT NULL CHECK(cohort IN ('squad','target')),
    active INTEGER NOT NULL CHECK(active IN (0,1)),
    last_seen_game_date TEXT,
    source_export TEXT,
    PRIMARY KEY(career,player_key,cohort)
);
CREATE INDEX IF NOT EXISTS ix_current_cohort ON cohort_membership(career,cohort,active);
CREATE TABLE IF NOT EXISTS career_chronology (
    career TEXT PRIMARY KEY,
    latest_game_date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS career_club (
    career TEXT PRIMARY KEY,
    club_uid TEXT NOT NULL,
    manager_staff_uid TEXT
);
'''


def log(msg):
    print(f'[{datetime.now().astimezone().isoformat(timespec="seconds")}] {msg}',flush=True)


def sha_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):
            h.update(block)
    return h.hexdigest()


def signature(path: Path):
    s=path.stat()
    return (s.st_size,s.st_mtime_ns)


def checked_copy(src: Path, dst: Path):
    before=signature(src)
    shutil.copyfile(src,dst)
    after=signature(src)
    if before!=after or dst.stat().st_size!=before[0]:
        raise RuntimeError('FM modified the save during copying; retrying later')
    return sha_file(dst)


def fmsave(*args):
    exe=shutil.which('fmsave')
    if not exe:
        raise RuntimeError('fmsave is not on PATH: run python -m pip install --upgrade fmsave')
    p=subprocess.run([exe,*args],text=True,capture_output=True,encoding='utf-8')
    if p.returncode:
        raise RuntimeError(f'fmsave failed: {(p.stderr or p.stdout)[-1800:]}')
    if p.stderr.strip():
        log('fmsave: '+p.stderr.strip()[-350:])
    return p.stdout


def read_csv(path):
    with path.open('r',encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        return reader.fieldnames or [],list(reader)


def find_export(directory,pattern):
    if directory is None:
        return None
    if not directory.is_dir():
        return None
    matches=[p for p in directory.glob(pattern) if p.is_file()]
    return max(matches,key=lambda p:(p.stat().st_mtime_ns,p.name)) if matches else None


def export_candidates(path):
    """Return exact F9 rows, plus the file's digest. Unique ID is optional."""
    if path is None:
        return [], '-'
    fields, rows = read_csv(path)
    fields = {f.strip().casefold() for f in fields}
    has_id = bool(fields & {'unique id', 'uniqueid', 'unique_id'})
    if not has_id and not {'player', 'age', 'club'} <= fields and not {'name', 'age', 'club'} <= fields:
        raise ValueError(f'{path.name}: Without Unique ID, the export must contain Player, Age and Club')
    if not has_id and any(not (r.get('Player') or r.get('Name')) or not r.get('Age') for r in rows):
        raise ValueError(f'{path.name}: Missing name or age; cannot match this export safely')
    return rows, sha_file(path)


def norm(s):
    """Compare displayed names and clubs despite case, accents or punctuation."""
    s = unicodedata.normalize('NFKD', str(s or '')).casefold()
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return ' '.join(re.findall(r'[^\W_]+', s, flags=re.UNICODE))


def club_of(row):
    value = row.get('club_name') or row.get('Club') or ''
    return '' if norm(value) in ('', 'free agent', 'unattached', 'none', 'n a') or str(value).strip() == '-' else norm(value)


def name_of(row):
    return norm(row.get('Player') or row.get('Name') or row.get('name'))


def attrs_agree(exported, world):
    """(comparable, agreement): relevant visible 1-20 attributes within one point."""
    aliases = {'team work': 'teamwork'}
    scores = []
    for title, value in exported.items():
        key = norm(title)
        key = aliases.get(key, key.replace(' ', '_'))
        field = 'attributes_' + key
        if field not in world or not world[field] or not value:
            continue
        try:
            a, b = int(str(value).strip()), int(world[field])
        except (ValueError, TypeError):
            continue
        if 1 <= a <= 20 and 1 <= b <= 20:
            scores.append(abs(a - b) <= 1)
    return len(scores), sum(scores) / len(scores) if scores else 0.0


def resolve_name_row(exported, by_name_age):
    """Fail closed on duplicates; permit a club-label mismatch only with evidence from attributes."""
    name = name_of(exported)
    try:
        age = int(str(exported.get('Age') or '').strip())
    except ValueError:
        return None, 'missing or invalid age'
    if not name:
        return None, 'missing name'
    candidates = by_name_age.get((name, age), [])
    if not candidates:
        return None, 'no name/age match in save'
    display_club = club_of(exported)
    exact = [p for p in candidates if club_of(p) == display_club]
    if len(exact) == 1:
        return exact[0], 'name+age+club'
    pool = exact if exact else candidates
    ranked = sorted(((attrs_agree(exported, p), p) for p in pool),
                    key=lambda v: (v[0][1], v[0][0]), reverse=True)
    if ranked:
        (n, rate), winner = ranked[0]
        runner = ranked[1][0][1] if len(ranked) > 1 else -1
        if n >= 5 and rate >= 0.8 and rate - runner >= 0.15:
            return winner, 'attributes-confirmed' if exact else 'attributes-confirmed (club differs)'
    return None, 'ambiguous name/age or club (attributes insufficient)'

def identity(row):
    return '|'.join((row['uid'],row.get('unique_id') or '',row.get('birth_date') or ''))


def choose_rows(world_csv, candidates, managed_uid):
    fields, world = read_csv(world_csv)
    required = {'uid','unique_id','birth_date','name','ability_current','ability_potential',
                'club_uid','loan_parent_club_uid'}
    if not required <= set(fields):
        raise ValueError('fmsave export columns changed; expected '+', '.join(sorted(required)))
    # A verified parent UID is sufficient to retain a possible owned player.
    # The bridge classifies a missing/contradictory loan flag as unknown.
    squad = [r for r in world if club_uid(r.get('club_uid')) == managed_uid or
             club_uid(r.get('loan_parent_club_uid')) == managed_uid]
    if not any(club_uid(r.get('club_uid')) == managed_uid for r in squad):
        raise ValueError('Managed-club export has no Rangers players; verify the save is your Rangers career')
    rows = {identity(r): r for r in squad}
    membership = {k: {'squad'} for k in rows}
    if not candidates:
        return rows, membership, 0
    by_id = defaultdict(dict)
    by_name_age = defaultdict(list)
    for r in world:
        for k in ('uid','unique_id'):
            token = (r.get(k) or '').strip()
            if token:
                by_id[token][identity(r)] = r
        if r.get('age'):
            try:
                by_name_age[(name_of(r),int(r['age']))].append(r)
            except ValueError:
                continue
    missing = []
    methods = defaultdict(int)
    for c in candidates:
        token = next(((v or '').strip() for k, v in c.items()
                      if k.strip().casefold() in ('unique id','uniqueid','unique_id') and (v or '').strip()), None)
        candidate = None
        method = ''
        if token:
            matches = list(by_id.get(token, {}).values())
            if len(matches) == 1:
                candidate, method = matches[0], 'id'
            elif len(matches) > 1:
                matches = [p for p in matches if name_of(p) == name_of(c)]
                if len(matches) == 1:
                    candidate, method = matches[0], 'id+name'
        if candidate is None:
            candidate, method = resolve_name_row(c, by_name_age)
        if candidate is None:
            missing.append(f"{c.get('Player') or c.get('Name') or token or '(unknown)'} ({c.get('Age') or '?'}; {c.get('Club') or '?'}): {method}")
            continue
        key = identity(candidate)
        rows[key] = candidate
        membership.setdefault(key,set()).add('target')
        methods[method] += 1
    found = sum('target' in cs for cs in membership.values())
    if candidates and (found == 0 or (len(candidates) >= 10 and found < 0.6 * len(candidates))):
        raise ValueError(f'Only {found}/{len(candidates)} filtered players could be matched; refusing to replace the active target list. '
                         f'Examples: {"; ".join(missing[:3])}')
    if methods:
        log('Selection matches: ' + ', '.join(f'{k}={v}' for k,v in sorted(methods.items())))
    if missing:
        log(f'WARNING: {len(missing)}/{len(candidates)} export rows were not matched. No identities were guessed.')
        for reason in missing[:12]:
            log('  unmatched: '+reason)
        if len(missing) > 12:
            log(f'  ...and {len(missing)-12} more')
    return rows, membership, found

def important(row):
    return {k:v for k,v in row.items() if v not in (None,'') and
            (k in BASE_FIELDS or k.startswith(FIELD_PREFIXES))}


def optional_int(v):
    try:return int(v) if v else None
    except(ValueError,TypeError):return None


def valid_game_date(value):
    """Only canonical, calendar-valid ISO dates can establish chronology."""
    if not isinstance(value,str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',value):
        return None
    try:
        return datetime.strptime(value,'%Y-%m-%d').date().isoformat()
    except ValueError:
        return None


def initialise_chronology(db):
    """Backfill unmigrated careers from all dated evidence, including inactive cohorts."""
    with db:
        db.execute('BEGIN IMMEDIATE')
        evidence=db.execute('''
            SELECT s.career,s.game_date FROM snapshots s
            WHERE NOT EXISTS (SELECT 1 FROM career_chronology c WHERE c.career=s.career)
            UNION
            SELECT m.career,m.last_seen_game_date FROM cohort_membership m
            WHERE NOT EXISTS (SELECT 1 FROM career_chronology c WHERE c.career=m.career)
        ''')
        latest={}
        for career,value in evidence:
            date=valid_game_date(value)
            if date and date>latest.get(career,''):
                latest[career]=date
        db.executemany('INSERT INTO career_chronology(career,latest_game_date) VALUES (?,?)',
                       latest.items())


def connect(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=60)
    db.execute('PRAGMA busy_timeout=60000')
    db.execute('PRAGMA journal_mode=WAL')
    db.executescript(SCHEMA)
    initialise_chronology(db)
    return db


def managed_identity(path):
    _, rows = read_csv(path)
    if len(rows) != 1:
        raise ValueError('Expected exactly one managed club in fmsave metadata')
    row = rows[0]
    uid = club_uid(row.get('club_uid'))
    if not uid or not rangers_names(row.get('club_name'),row.get('club_short_name')):
        raise ValueError('Managed club is not unambiguously Rangers')
    manager = row.get('manager_staff_uid')
    if manager and not club_uid(manager):
        raise ValueError('Invalid managed-club manager identifier')
    return uid, club_uid(manager)


def verify_club_record(path, managed_uid):
    _, rows = read_csv(path)
    if (len(rows) != 1 or club_uid(rows[0].get('uid')) != managed_uid or
            not rangers_names(rows[0].get('name'),rows[0].get('short_name'))):
        raise ValueError('Managed Rangers identifier conflicts with fmsave club record')


def confirm_career_club(db,career,managed):
    uid, manager = managed
    previous = db.execute('SELECT club_uid,manager_staff_uid FROM career_club WHERE career=?',(career,)).fetchone()
    if previous:
        if previous[0] != uid or (previous[1] and manager and previous[1] != manager):
            raise ValueError('Managed club or manager identifier conflicts with this career')
        return
    # Existing databases predate the binding. Check their active squad evidence
    # before establishing an identifier, without rewriting any historical rows.
    legacy = [json.loads(row[0]) for row in db.execute('''
        SELECT p.record_json FROM cohort_membership m
        JOIN player_latest l ON l.career=m.career AND l.player_key=m.player_key
        JOIN player_versions p ON p.snapshot_id=l.snapshot_id AND p.player_key=l.player_key
        WHERE m.career=? AND m.cohort='squad' AND m.active=1
    ''',(career,))]
    if legacy and rangers_ids(legacy) != {uid}:
        raise ValueError('Cannot reconcile existing career club identifiers with managed Rangers club')


def import_selection(db,career,source,save_hash,sel_hash,metadata,rows,membership,export,managed):
    info=metadata.get('info',metadata) if isinstance(metadata,dict) else None
    date=valid_game_date(info.get('game_date') or info.get('in_game_date')) if isinstance(info,dict) else None
    if date is None:
        raise ValueError('Missing or invalid game date; refusing to import without YYYY-MM-DD chronology')
    build=info.get('build')
    with db:
        # Serialise the chronology check with the writes, including concurrent watchers.
        db.execute('BEGIN IMMEDIATE')
        confirm_career_club(db,career,managed)
        latest=db.execute('SELECT latest_game_date FROM career_chronology WHERE career=?',(career,)).fetchone()
        if latest and date<latest[0]:
            log(f'Skipping older rotating save for {career}: {date} < {latest[0]}')
            return None
        # First filter by cohort, then compare only this small set with the database.
        previous=dict(db.execute('SELECT player_key,record_hash FROM player_latest WHERE career=?',(career,)))
        changes=[]
        for key,row in rows.items():
            payload=json.dumps(important(row),ensure_ascii=False,sort_keys=True,separators=(',',':'))
            digest=hashlib.sha256(payload.encode('utf-8')).hexdigest()
            if previous.get(key)!=digest:
                changes.append((key,row,digest,payload))
        if changes:
            c=db.execute('''INSERT INTO snapshots
               (career,source_file,source_sha256,selection_sha256,game_date,game_build,imported_utc,player_count,changed_count)
               VALUES (?,?,?,?,?,?,?,?,?)''',
                (career,str(source),save_hash,sel_hash,date,
                str(build) if build else None,datetime.now(timezone.utc).isoformat(),len(rows),len(changes)))
            snapshot_id=c.lastrowid
            db.executemany('''INSERT INTO player_versions
               (snapshot_id,career,player_key,player_uid,unique_id,name,club_uid,current_ability,potential_ability,wage,record_hash,record_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
               ((snapshot_id,career,key,r['uid'],r.get('unique_id'),r.get('name'),r.get('club_uid'),
                 optional_int(r.get('ability_current')),optional_int(r.get('ability_potential')),
                 optional_int(r.get('contract_wage')),digest,payload)
                for key,r,digest,payload in changes))
            db.executemany('''INSERT INTO player_latest(career,player_key,record_hash,snapshot_id)
               VALUES (?,?,?,?) ON CONFLICT(career,player_key) DO UPDATE SET
               record_hash=excluded.record_hash,snapshot_id=excluded.snapshot_id''',
               ((career,key,digest,snapshot_id) for key,_,digest,_ in changes))
        # Record cohort membership independently of player changes, including an empty target list.
        db.execute('UPDATE cohort_membership SET active=0 WHERE career=?',(career,))
        db.executemany('''INSERT INTO cohort_membership
            (career,player_key,cohort,active,last_seen_game_date,source_export)
            VALUES (?,?,?,1,?,?) ON CONFLICT(career,player_key,cohort)
            DO UPDATE SET active=1,last_seen_game_date=excluded.last_seen_game_date,
                          source_export=excluded.source_export''',
            ((career,key,cohort,date,str(export) if cohort=='target' and export else None)
             for key,cohorts in membership.items() for cohort in cohorts))
        db.execute('''INSERT INTO career_chronology(career,latest_game_date) VALUES (?,?)
            ON CONFLICT(career) DO UPDATE SET latest_game_date=excluded.latest_game_date''',
                   (career,date))
        db.execute('''INSERT INTO career_club(career,club_uid,manager_staff_uid) VALUES (?,?,?)
            ON CONFLICT(career) DO UPDATE SET manager_staff_uid=COALESCE(career_club.manager_staff_uid,excluded.manager_staff_uid)''',
                   (career,*managed))
    return (len(rows),len(changes))


def process(db,source,career,export):
    log('Processing '+source.name+(f'; filter {export.name}' if export else '; squad only'))
    with tempfile.TemporaryDirectory(prefix='fm-rangers-') as td:
        temp=Path(td)
        copy=temp/'snapshot.fm'
        save_hash=checked_copy(source,copy)
        candidates,selection_hash=export_candidates(export)
        # Do not skip an already-seen save+filter pair: re-selecting a prior filter
        # must reactivate its cohort even if no player attributes have changed.
        metadata=json.loads(fmsave('info',str(copy),'--json'))
        managed_file=temp/'managed.csv'
        fmsave('export',str(copy),'managed-clubs','--all','-o',str(managed_file),'--strict')
        managed=managed_identity(managed_file)
        club_file=temp/'club.csv'
        fmsave('export',str(copy),'clubs','--club',managed[0],'-o',str(club_file),'--strict')
        verify_club_record(club_file,managed[0])
        world_file=temp/'all.csv'
        # fmsave's managed-club player scope uses the current club, excluding
        # players registered elsewhere on loan. Read all players transiently.
        log('Starting temporary full-world player export')
        export_started=time.monotonic()
        fmsave('export',str(copy),'players','--all','-o',str(world_file),'--strict')
        log(f'Temporary full-world player export completed in {time.monotonic()-export_started:.2f}s; '
            f'{world_file.stat().st_size/1024**2:.2f} MiB (temporary)')
        rows,membership,found=choose_rows(world_file,candidates,managed[0])
        result=import_selection(db,career,source,save_hash,selection_hash,metadata,rows,membership,export,managed)
        if result is None:
            return False
        n,k=result
        log(f'Accepted: {sum("squad" in c for c in membership.values())} squad, '
            f'{found}/{len(candidates)} filtered targets; {k} player versions changed; '
            f'database {db.execute("PRAGMA database_list").fetchone()[2]}')
    return True


def list_saves(args):
    if args.file:
        return [args.file] if args.file.is_file() else []
    candidates=[p for p in args.watch_dir.glob(args.pattern) if p.is_file()]
    return [max(candidates,key=lambda p:p.stat().st_mtime_ns)] if candidates else []


def run(args):
    db=connect(args.db)
    try:
        log('Watching Rangers saves (read-only). A filtered F9 export updates the target cohort.')
        if args.exports_dir and not find_export(args.exports_dir,args.export_pattern):
            log('No filtered CSV export yet; importing Rangers squad only. Configure exporter prefix rangers and press F9 on filtered Player Search.')
        if args.once:
            for source in list_saves(args):
                stamp=signature(source)
                exp=find_export(args.exports_dir,args.export_pattern)
                e_stamp=(str(exp),signature(exp)) if exp else None
                time.sleep(3)
                if signature(source)!=stamp or (str(find_export(args.exports_dir,args.export_pattern)) if find_export(args.exports_dir,args.export_pattern) else None)!=(str(exp) if exp else None) or (exp and signature(exp)!=e_stamp[1]):
                    raise RuntimeError('Save or export still being written; retry --once later')
                process(db,source,args.career,exp)
            return 0
        observed={};processed={}
        while True:
            exp=find_export(args.exports_dir,args.export_pattern)
            e_sig=(str(exp),signature(exp)) if exp else ('',None)
            for source in list_saves(args):
                try:
                    sig=(signature(source),e_sig)
                    now=time.monotonic()
                    prior=observed.get(source)
                    if not prior or prior[0]!=sig:
                        observed[source]=(sig,now)
                        continue
                    if now-prior[1]<args.stable_seconds or processed.get(source)==sig:
                        continue
                    try:
                        process(db,source,args.career,exp)
                        processed[source]=sig
                    except (OSError,RuntimeError,ValueError,sqlite3.Error,subprocess.SubprocessError) as e:
                        log('Import error; will retry: '+str(e))
                        observed[source]=(sig,now)
                except OSError as e:
                    log('File stat error: '+str(e))
            time.sleep(args.interval)
    except KeyboardInterrupt:
        log('Stopped')
        return 0
    finally:
        db.close()


def show_status(path,career):
    db=connect(path)
    try:
        print(f'Database: {path} / career: {career}')
        for cohort in ('squad','target'):
            n=db.execute('SELECT COUNT(*) FROM cohort_membership WHERE career=? AND cohort=? AND active=1',
                         (career,cohort)).fetchone()[0]
            print(f'Active {cohort}: {n}')
        rows=db.execute('''SELECT p.name, p.club_uid FROM cohort_membership c
              JOIN player_latest l ON c.career=l.career AND c.player_key=l.player_key
              JOIN player_versions p ON p.snapshot_id=l.snapshot_id AND p.player_key=l.player_key
              WHERE c.career=? AND c.cohort='target' AND c.active=1
              ORDER BY p.name LIMIT 60''',(career,)).fetchall()
        for name,club_uid in rows:
            print('  '+name+' (club UID '+str(club_uid)+')')
    finally:
        db.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--file',type=Path,help='One overwritten .fm save')
    g.add_argument('--watch-dir',type=Path,help='Watch a folder of rotating saves')
    p.add_argument('--pattern',default='*Rangers*.fm',help='Autosave filename glob with --watch-dir')
    p.add_argument('--career',default='rangers')
    p.add_argument('--db',type=Path,default=DEFAULT_DB)
    p.add_argument('--exports-dir',type=Path,help='FM View Exporter CSV output folder (optional; squad only if absent)')
    p.add_argument('--export-pattern',default='rangers*player-database*.csv',help='Glob for the filtered Rangers F9 exports')
    p.add_argument('--interval',type=float,default=10)
    p.add_argument('--stable-seconds',type=float,default=30)
    p.add_argument('--once',action='store_true')
    p.add_argument('--status',action='store_true',help='Print current squad/target counts and active targets; do not parse the save')
    a=p.parse_args()
    if a.interval<=0 or a.stable_seconds<0:p.error('Bad interval or stable period')
    if a.file and not a.file.is_file():p.error(f'Save file not found: {a.file}')
    if a.watch_dir and not a.watch_dir.is_dir():p.error(f'Save directory not found: {a.watch_dir}')
    # The optional exporter directory is often created only after the first F9 export.
    # A missing folder must not prevent the squad-only autosave watcher from running;
    # find_export() will detect it automatically if it appears later.
    if a.exports_dir and not a.exports_dir.is_dir() and not a.status:
        log(f'FM View Exporter folder not found yet: {a.exports_dir}. '
            'Continuing with Rangers squad only; transfer candidates will be picked up after an F9 export.')
    if a.status:
        show_status(a.db,a.career)
        return 0
    try:return run(a)
    except (OSError,RuntimeError,ValueError,sqlite3.Error,subprocess.SubprocessError) as e:
        log('Error: '+str(e))
        return 1

if __name__=='__main__':
    sys.exit(main())

