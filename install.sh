#!/bin/sh
# MistriaMulti installer for Linux (Debian/Ubuntu, Steam Deck desktop mode).  Run it once:   ./install.sh
# After that you only start the game from Steam: hosting and joining are chosen in the game's own Multiplayer menu.
#
#   ./install.sh               install (safe to run again)
#   ./install.sh --update      download the latest GitHub release and update the programs and the mod files (safe to run again).
#                              Then it runs MOMI's command-line installer if you set that up and agree, else it tells you what to click.
#                              The same thing:  mistrimulti-manager update
#   ./install.sh --momi-cli PATH [--always]   remember MOMI's command-line program (ModsOfMistriaInstaller-cli-linux) for --update;
#                              with --always it may also run without a question when an update starts without a terminal; "none" forgets both
#   ./install.sh --update --result FILE   no questions, for programs (the game's Update button): progress and result as state=/version=/message=/error=
#                              lines in FILE (docs/RELEASES.md). MOMI's installer runs only with --always set earlier and MISTRIMULTI_NO_MOMI unset.
#   ./install.sh --dry-run     show what would be done, change nothing
#   ./install.sh --uninstall   put Steam's settings back and remove the program folder
#   ./install.sh --yes         allow it to run the one `sudo apt-get install` it may need (nasm, binutils)
#
# Environment: MISTRIMULTI_DIR (program folder, default ~/.local/share/mistrimulti),
#              MISTRIMULTI_APPID (Steam app id, default: found from the game's appmanifest, else 2142790),
#              MISTRIMULTI_STEAM_RUNNING=1|0 (override the "is Steam running" check),
#              MISTRIMULTI_RELEASE_BASE (tests only: a web server that mimics the release layout, see docs/RELEASES.md).
# The game's launcher starts a quiet "mistrimulti-update.sh --daily <mod data folder>" in the background (at most one check a day):
# it only writes update.json for the in-game badge. A line "check=off" in <mod data folder>/update.cfg turns it off.
set -eu

exec 3<&0
SRC=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SELF=$SRC/$(basename -- "$0")
DEFAULT_APPID=2142790          # Fields of Mistria; also the compatdata id used in tests/test_launcher_linux.py
GAME_NAME='Fields of Mistria'
DIR=${MISTRIMULTI_DIR:-$HOME/.local/share/mistrimulti}
BINS='mistrimulti-launcher mistrimulti-manager mistrimulti-helper-linux mistrimulti-steam-id-linux'
BACKUP_SUFFIX=.mistrimulti-backup
APPLIED_SUFFIX=.mistrimulti-applied
REPO=tomrocksyou/MistriaMulti

DRY=0 YES=0 UNINSTALL=0 UPDATE=0 DAILY='' MOMICLI='' RESULT='' ALWAYS=0
while [ $# -gt 0 ]; do
    case $1 in
        --dry-run) DRY=1 ;;
        --yes|-y) YES=1 ;;
        --uninstall) UNINSTALL=1 ;;
        --update) UPDATE=1 ;;
        --daily) [ $# -ge 2 ] || exit 2; DAILY=$2; shift ;;
        --result) [ $# -ge 2 ] || exit 2; RESULT=$2; UPDATE=1; shift ;;
        --always) ALWAYS=1 ;;
        --momi-cli) [ $# -ge 2 ] || { echo "--momi-cli needs a path (or the word none)" >&2; exit 2; }; MOMICLI=$2; shift ;;
        -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $1 (try --help)" >&2; exit 2 ;;
    esac
    shift
done

TMP=$(mktemp -d "${TMPDIR:-/tmp}/mistrimulti-install.XXXXXX")
trap 'rm -rf "$TMP"' EXIT INT TERM

LASTMSG=''
say() { printf '%s\n' "$*"; LASTMSG=$*; }
act() { if [ "$DRY" = 1 ]; then say "[dry run] would: $*"; else say "$*"; fi; }
SUMMARY=$TMP/summary
: > "$SUMMARY"
note() { printf '  - %s\n' "$*" >> "$SUMMARY"; }

LAUNCH_LINE="\"$DIR/mistrimulti-launcher\" --steam %command%"

# ---------------------------------------------------------------- Steam discovery
steam_running() {
    case ${MISTRIMULTI_STEAM_RUNNING:-} in 1) return 0 ;; 0) return 1 ;; esac
    for comm in /proc/[0-9]*/comm; do
        [ -r "$comm" ] || continue
        read -r name < "$comm" 2>/dev/null || continue
        case $name in steam|steamwebhelper) return 0 ;; esac
    done
    return 1
}

# Steam roots (real paths, no duplicates) -> $TMP/roots ; library folders -> $TMP/libs
find_steam() {
    : > "$TMP/roots"; : > "$TMP/libs"
    for cand in "$HOME/.steam/steam" "$HOME/.steam/debian-installation" "$HOME/.local/share/Steam" \
                "$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam" \
                "$HOME/.var/app/com.valvesoftware.Steam/.steam/steam"; do
        [ -d "$cand/steamapps" ] || [ -d "$cand/userdata" ] || continue
        real=$(CDPATH= cd -P -- "$cand" 2>/dev/null && pwd -P) || continue
        grep -qxF -- "$real" "$TMP/roots" 2>/dev/null || printf '%s\n' "$real" >> "$TMP/roots"
    done
    while IFS= read -r root; do
        printf '%s\n' "$root" >> "$TMP/libs"
        vdf=$root/steamapps/libraryfolders.vdf
        [ -f "$vdf" ] && sed -n 's/^[[:space:]]*"path"[[:space:]]*"\(.*\)"[[:space:]]*$/\1/p' "$vdf" | sed 's/\\\\/\\/g' >> "$TMP/libs"
    done < "$TMP/roots"
    sort -u "$TMP/libs" > "$TMP/libs.u"
}

# Sets APPID and GAMEDIR (GAMEDIR empty when the game is not installed in any library).
find_game() {
    APPID=${MISTRIMULTI_APPID:-$DEFAULT_APPID}
    GAMEDIR=''
    FOUND_MANIFEST=0
    while IFS= read -r lib; do
        [ -n "$lib" ] || continue
        manifest=$lib/steamapps/appmanifest_$APPID.acf
        if [ ! -f "$manifest" ] && [ -z "${MISTRIMULTI_APPID:-}" ]; then
            for m in "$lib"/steamapps/appmanifest_*.acf; do
                [ -f "$m" ] || continue
                n=$(sed -n 's/^[[:space:]]*"name"[[:space:]]*"\(.*\)".*/\1/p' "$m" | head -n 1)
                if [ "$n" = "$GAME_NAME" ]; then
                    manifest=$m
                    APPID=$(sed -n 's/^[[:space:]]*"appid"[[:space:]]*"\([0-9][0-9]*\)".*/\1/p' "$m" | head -n 1)
                    [ -n "$APPID" ] || APPID=$DEFAULT_APPID
                    break
                fi
            done
        fi
        [ -f "$manifest" ] || continue
        inst=$(sed -n 's/^[[:space:]]*"installdir"[[:space:]]*"\(.*\)".*/\1/p' "$manifest" | head -n 1)
        [ -n "$inst" ] || inst=$GAME_NAME
        FOUND_MANIFEST=1
        if [ -d "$lib/steamapps/common/$inst" ]; then GAMEDIR=$lib/steamapps/common/$inst; return 0; fi
    done < "$TMP/libs.u"
    return 0
}

# ---------------------------------------------------------------- localconfig.vdf editing
# vdf_awk get|set FILE : the parser. MM_APPID, MM_WANT (already escaped for vdf) and MM_STATE come from the environment
# (not -v, which would process backslash escapes).
# get prints one of: apps-missing | app-missing | no-option | option:<raw value>
# set writes the edited file to stdout (state: option = replace/clear, no-option = add, app-missing = add the app block).
vdf_awk() {
    MM_MODE=$1 awk '
    function tok(t,   n) { match(t, /^"([^"\\]|\\.)*"/); n = RLENGTH; return substr(t, 2, n - 2) }
    function indent(s) { match(s, /^[ \t]*/); return substr(s, 1, RLENGTH) }
    BEGIN { mode = ENVIRON["MM_MODE"]; appid = tolower(ENVIRON["MM_APPID"]); want = ENVIRON["MM_WANT"]; state = ENVIRON["MM_STATE"]
            appspath = "userlocalconfigstore/software/valve/steam/apps"; apppath = appspath "/" appid; depth = 0; done = 0 }
    {
        line = $0; t = line; sub(/^[ \t]+/, "", t); sub(/[ \t\r]+$/, "", t)
        out = 1; extra = ""
        if (t ~ /^"([^"\\]|\\.)*"$/) { pending = tolower(tok(t)) }
        else if (t == "{") {
            depth++; stack[depth] = pending; pending = ""
            path = ""; for (i = 1; i <= depth; i++) path = path (i > 1 ? "/" : "") stack[i]
            if (path == appspath) { apps_found = 1
                if (mode == "set" && state == "app-missing" && !done) { ind = indent(line)
                    extra = ind "\t\"" ENVIRON["MM_APPID"] "\"\n" ind "\t{\n" ind "\t\t\"LaunchOptions\"\t\t\"" want "\"\n" ind "\t}"; done = 1 } }
            else if (path == apppath) { app_found = 1
                if (mode == "set" && state == "no-option" && !done) { ind = indent(line)
                    extra = ind "\t\"LaunchOptions\"\t\t\"" want "\""; done = 1 } }
        }
        else if (t == "}") { depth--; pending = "" }
        else if (t ~ /^"([^"\\]|\\.)*"[ \t]+"([^"\\]|\\.)*"$/) {
            pending = ""
            path = ""; for (i = 1; i <= depth; i++) path = path (i > 1 ? "/" : "") stack[i]
            if (path == apppath && tolower(tok(t)) == "launchoptions" && !opt_found) {
                opt_found = 1; rest = t; match(rest, /^"([^"\\]|\\.)*"/); rest = substr(rest, RLENGTH + 1); sub(/^[ \t]+/, "", rest)
                raw = substr(rest, 2, length(rest) - 2)
                if (mode == "set" && state == "option") { out = 0; print indent(line) "\"LaunchOptions\"\t\t\"" want "\""; done = 1 }
            }
        } else pending = ""
        if (mode == "set") { if (out) print line; if (extra != "") print extra }
    }
    END { if (mode == "get") { if (!apps_found) print "apps-missing"; else if (!app_found) print "app-missing"
                               else if (!opt_found) print "no-option"; else print "option:" raw }
          if (mode == "set" && !done) exit 3 }
    ' "$2"
}

vdf_escape() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
vdf_unescape() { printf '%s' "$1" | sed 's/\\"/"/g; s/\\\\/\\/g'; }
vdf_balanced() {  # same number of { and } lines
    o=$(grep -c '^[[:space:]]*{[[:space:]]*$' "$1" || true); c=$(grep -c '^[[:space:]]*}[[:space:]]*$' "$1" || true)
    [ "$o" = "$c" ]
}

# apply_launch_option FILE
apply_launch_option() {
    f=$1
    want=$(vdf_escape "$LAUNCH_LINE")
    state=$(MM_APPID=$APPID MM_WANT=$want vdf_awk get "$f") || state=error
    case $state in
        apps-missing|error)
            say "  $f: no 'apps' section found (Steam has not written one yet?). Not changed."
            note "Could not edit $f automatically; paste the launch option by hand (see below)."
            MANUAL=1; return 0 ;;
        option:*)
            raw=${state#option:}
            if [ "$raw" = "$want" ]; then say "  $f: launch option already set."; return 0; fi
            if [ -n "$raw" ]; then
                say "  $f: Fields of Mistria already has this launch option:"
                say "      $(vdf_unescape "$raw")"
                if [ "$DRY" = 1 ]; then say "[dry run] would ask whether to replace it"; return 0; fi
                printf '  Replace it with the MistriaMulti one? (the old one stays in the backup) [y/N] '
                ans=n; read -r ans <&3 || ans=n
                case $ans in y|Y|yes|YES) ;; *)
                    say "  Left unchanged. To use MistriaMulti, put this in Steam yourself, ahead of or instead of the old one:"
                    say "      $LAUNCH_LINE"
                    note "Existing Steam launch option kept in $f; MistriaMulti's line was NOT added."
                    MANUAL=1; return 0 ;; esac
            fi
            setstate=option ;;
        no-option) setstate=no-option ;;
        app-missing) setstate=app-missing ;;
    esac
    if [ "$DRY" = 1 ]; then act "back up $f and set the Fields of Mistria launch option in it"; return 0; fi
    backup=$f$BACKUP_SUFFIX applied=$f$APPLIED_SUFFIX
    if [ ! -f "$backup" ] || [ ! -f "$applied" ] || [ "$(cksum < "$f")" != "$(cat "$applied")" ]; then
        cp -p "$f" "$backup"; say "  Backed up $f to $backup"
    fi
    new=$TMP/localconfig.new
    if ! MM_APPID=$APPID MM_WANT=$want MM_STATE=$setstate vdf_awk set "$f" > "$new" || ! vdf_balanced "$new" \
       || [ "$(MM_APPID=$APPID MM_WANT=$want vdf_awk get "$new")" != "option:$want" ]; then
        say "  $f: the edit did not come out right, so it was NOT applied (the file is unchanged)."
        note "Could not edit $f safely; paste the launch option by hand."
        MANUAL=1; return 0
    fi
    cat "$new" > "$f"
    cksum < "$f" > "$applied"
    say "  Set the launch option in $f"
    EDITED=$((EDITED + 1))
}

# ---------------------------------------------------------------- uninstall
do_uninstall() {
    find_steam
    find_game
    if steam_running; then
        say 'Steam is running. Close Steam completely, then run ./install.sh --uninstall again.'
        say '(Steam would otherwise write its old settings back, and the launch option would point at a removed folder.)'
        exit 1
    fi
    while IFS= read -r root; do
        for f in "$root"/userdata/*/config/localconfig.vdf; do
            [ -f "$f" ] || continue
            backup=$f$BACKUP_SUFFIX applied=$f$APPLIED_SUFFIX
            [ -f "$backup" ] || continue
            if [ -f "$applied" ] && [ "$(cksum < "$f")" = "$(cat "$applied")" ]; then
                act "restore $f from $backup"
                [ "$DRY" = 1 ] || { cat "$backup" > "$f"; rm -f "$backup" "$applied"; }
            else
                # Steam changed the file since we edited it: only take our own launch option out.
                                want=$(vdf_escape "$LAUNCH_LINE")
                cur=$(MM_APPID=$APPID MM_WANT=$want vdf_awk get "$f" || true)
                if [ "$cur" = "option:$want" ]; then
                    act "clear MistriaMulti's launch option in $f (the file changed since install, so the backup $backup is kept, not restored)"
                    if [ "$DRY" != 1 ]; then
                        if MM_APPID=$APPID MM_WANT= MM_STATE=option vdf_awk set "$f" > "$TMP/lc.new" && vdf_balanced "$TMP/lc.new"; then
                            cat "$TMP/lc.new" > "$f"; rm -f "$applied"
                        else say "  could not edit $f; remove the launch option in Steam by hand."; fi
                    fi
                else
                    say "  $f no longer has MistriaMulti's launch option; leaving it alone."
                    [ "$DRY" = 1 ] || rm -f "$applied"
                fi
            fi
        done
    done < "$TMP/roots"
    link=$HOME/.local/bin/mistrimulti
    if [ -L "$link" ] && [ "$(readlink "$link")" = "$DIR/mistrimulti-manager" ]; then
        act "remove $link"; [ "$DRY" = 1 ] || rm -f "$link"
    fi
    if [ -d "$DIR" ]; then act "remove $DIR"; [ "$DRY" = 1 ] || rm -rf "$DIR"; else say "$DIR does not exist."; fi
    say 'The game mod (mods/mistrimulti in the game folder) was left alone: remove it with MOMI if you want it gone.'
    say 'Uninstalled.'
}

# ---------------------------------------------------------------- update from the latest GitHub release
# Layout and rules (the same as the Windows manager's, docs/RELEASES.md):
#   <releases>/latest/download/latest.txt     the list: version, SHA-256 of every file, a footer
#   raw.githubusercontent.com/<repo>/v<version>/mod/mistrimulti/<file>     the mod files (read from the tagged commit)
#   <releases>/download/v<version>/MistriaMulti-<version>-Linux.tar.gz      the Linux programs (hash in a "#linux-tar" line of the list)
# Nothing is installed unless the whole list is valid and every downloaded file matched its hash.
if [ -n "${MISTRIMULTI_RELEASE_BASE:-}" ]; then
    URL_LIST=$MISTRIMULTI_RELEASE_BASE/release/latest.txt
    PROTO=''
else
    URL_LIST=https://github.com/$REPO/releases/latest/download/latest.txt
    PROTO='--proto =https --proto-redir =https'
fi
url_mod() { if [ -n "${MISTRIMULTI_RELEASE_BASE:-}" ]; then echo "$MISTRIMULTI_RELEASE_BASE/$2"; else echo "https://raw.githubusercontent.com/$REPO/v$1/$2"; fi; }
url_tar() { if [ -n "${MISTRIMULTI_RELEASE_BASE:-}" ]; then echo "$MISTRIMULTI_RELEASE_BASE/dl/$2"; else echo "https://github.com/$REPO/releases/download/v$1/$2"; fi; }

# fetch URL OUTFILE MAXBYTES [CONNECT_SECONDS TOTAL_SECONDS]: 0 ok, 1 failed, 2 neither curl nor wget
fetch() {
    ct=${4:-10} tt=${5:-120}
    rm -f "$2"
    if command -v curl >/dev/null 2>&1; then
        # shellcheck disable=SC2086
        curl -fsSL --connect-timeout "$ct" --max-time "$tt" --max-filesize "$3" $PROTO -o "$2" "$1" 2>/dev/null || return 1
    elif command -v wget >/dev/null 2>&1; then
        wget -q -T "$tt" -t 1 -O "$2" "$1" 2>/dev/null || return 1
    else
        return 2
    fi
    [ -f "$2" ] || return 1
    [ "$(wc -c < "$2")" -le "$3" ] || { rm -f "$2"; return 1; }
    return 0
}

sha_of() { sha256sum "$1" | cut -d' ' -f1; }

# ver_cmp A B -> -1 (A older), 0, 1 (A newer); numbers compared group by group, missing groups are 0
ver_cmp() { awk -v a="$1" -v b="$2" 'BEGIN { na = split(a, x, "."); nb = split(b, y, "."); for (i = 1; i <= 4; i++) { p = (i <= na) ? x[i] + 0 : 0; q = (i <= nb) ? y[i] + 0 : 0; if (p < q) { print -1; exit } if (p > q) { print 1; exit } } print 0 }'; }

# check_list FILE: validates the whole list. On success: LIST_VERSION, $TMP/modfiles ("<hash> <path under mod/mistrimulti/>"), $TMP/linuxtar ("<hash> <name>", may be empty)
check_list() {
    f=$1
    [ "$(wc -c < "$f")" -le 30000 ] || return 1
    [ "$(tail -c 1 "$f" | od -An -tx1 | tr -d ' \n')" = 0a ] || return 1      # a list that lost its tail is rejected
    awk -v modout="$TMP/modfiles" -v tarout="$TMP/linuxtar" '
    function bad() { failed = 1; exit 1 }
    function hexok(h) { return length(h) == 64 && h !~ /[^0-9a-f]/ }
    BEGIN { n = 0; end = -1; ver = ""; man = 0; tars = 0; printf "" > modout; printf "" > tarout }
    { sub(/\r$/, "") }
    /^[ \t]*$/ { next }
    /^#/ {
        if ($1 == "#linux-tar") { if (NF != 3 || !hexok($2) || $3 !~ /^MistriaMulti-[0-9.]+-Linux\.tar\.gz$/ || tars++) bad(); print $2, $3 > tarout }
        next
    }
    end >= 0 { bad() }
    ver == "" {
        if (NF != 2 || $1 != "version" || $2 !~ /^[0-9]+(\.[0-9]+)*$/ || length($2) > 27) bad()
        k = split($2, g, "."); if (k > 4) bad(); for (i = 1; i <= k; i++) if (length(g[i]) > 5) bad()
        ver = $2; next
    }
    $1 == "end" && NF == 2 { if ($2 !~ /^[0-9]+$/ || $2 + 0 != n) bad(); end = $2; next }
    {
        if (NF != 2 || !hexok($1) || length($2) > 160 || seen[$2]++) bad()
        path = $2
        if (substr(path, 1, 16) == "mod/mistrimulti/") {
            rest = substr(path, 17); k = split(rest, c, "/"); if (k < 1) bad()
            for (i = 1; i <= k; i++) {
                if (c[i] !~ /^[A-Za-z0-9_-][A-Za-z0-9._-]*$/ || c[i] ~ /\.$/) bad()
            }
            if (rest == "manifest.toml") man = 1
            print $1, rest > modout; n++
        } else if (path ~ /^bin\/(MistriMulti\.exe|MistriMultiLauncher\.exe|mistrimulti-helper\.exe|mistrimulti-steam-id\.exe)$/) { n++ }
        else bad()
        if (n > 200) bad()
    }
    END { if (failed) exit 1; if (ver == "" || end < 0 || !man) exit 1; print ver }
    ' "$f" >"$TMP/listver" 2>/dev/null || return 1
    LIST_VERSION=$(cat "$TMP/listver")
    [ -n "$LIST_VERSION" ] || return 1
    [ -f "$TMP/linuxtar" ] || : > "$TMP/linuxtar"
    if [ -s "$TMP/linuxtar" ]; then
        [ "$(cut -d' ' -f2 "$TMP/linuxtar")" = "MistriaMulti-$LIST_VERSION-Linux.tar.gz" ] || return 1
    fi
    return 0
}

installed_mod_version() {    # $1 manifest path -> prints the version (digits and dots only), nothing if unknown
    [ -f "$1" ] || return 0
    v=$(sed -n 's/^version = "\([0-9][0-9.]*\)".*/\1/p' "$1" | head -n 1)
    printf '%s' "$v"
}

# --daily MODDATA: quiet, at most once a day, short timeouts. Writes MODDATA/update.json for the in-game badge. Never fails loudly.
do_daily() {
    md=$1
    [ -d "$md" ] || exit 0
    if [ -f "$md/update.cfg" ] && grep -q 'check=off' "$md/update.cfg" 2>/dev/null; then exit 0; fi
    now=$(date +%s 2>/dev/null) || exit 0
    last=$(sed -n 's/.*"checked":[ ]*\([0-9][0-9]*\).*/\1/p' "$md/update.json" 2>/dev/null | head -n 1)
    case $last in ''|*[!0-9]*) last='' ;; esac
    if [ -n "$last" ] && [ ${#last} -le 11 ] && [ "$last" -le "$now" ] && [ $((now - last)) -lt 86400 ]; then exit 0; fi
    fetch "$URL_LIST" "$TMP/latest.txt" 30000 4 6 || exit 0
    check_list "$TMP/latest.txt" || exit 0
    printf '{"v":1,"latest":"%s","checked":%s}\n' "$LIST_VERSION" "$now" > "$md/update.json.tmp" 2>/dev/null || exit 0
    mv -f "$md/update.json.tmp" "$md/update.json" 2>/dev/null || rm -f "$md/update.json.tmp"
    exit 0
}

valid_cli_name() { case $(basename -- "$1") in *-cli*|*-CLI*|*-Cli*) return 0 ;; esac; return 1; }

# --momi-cli PATH|none
do_momi_cli() {
    if [ "$1" = none ]; then rm -f "$DIR/momi-cli.path" "$DIR/momi-cli.auto"; say "MOMI's command-line program is forgotten. --update will tell you to press Install in MOMI instead."; exit 0; fi
    p=$1
    case $p in /*) ;; *) p=$(pwd)/$p ;; esac
    if [ ! -f "$p" ] || [ -L "$p" ] || [ ! -x "$p" ]; then
        say "$p is not an executable file. Download MOMI's command-line program (ModsOfMistriaInstaller-cli-linux), make it executable (chmod +x) and give its path."
        exit 1
    fi
    if ! valid_cli_name "$p"; then
        say "Only MOMI's command-line program (a file name with -cli in it) can be used here; $(basename -- "$p") is not."
        exit 1
    fi
    mkdir -p "$DIR"
    printf '%s\n' "$p" > "$DIR/momi-cli.path"
    say "Saved: $p"
    if [ "$ALWAYS" = 1 ]; then
        : > "$DIR/momi-cli.auto"
        say "--always: it may also run without a question when an update starts without a terminal (for example from the game's Update button,"
        say "unless that caller forbids it because the game is open). It rewrites the game's data file, so keep the game closed then."
    else
        rm -f "$DIR/momi-cli.auto"
    fi
    say "After a mod update, ./install.sh --update asks before it runs it (every time)."
    exit 0
}

# Is MOMI's command-line program set up and still what it was? Sets cli.
momi_cli_ok() {
    cli=''
    [ -f "$DIR/momi-cli.path" ] && read -r cli < "$DIR/momi-cli.path" || true
    [ -n "$cli" ] && [ -f "$cli" ] && [ ! -L "$cli" ] && [ -x "$cli" ] && valid_cli_name "$cli" && [ -n "$GAMEDIR" ]
}

# Runs it in the game folder: no arguments (per MOMI's source that installs every mod in the mods folder), EXIT_ON_COMPLETE=true so it
# does not wait for a key, no input, at most 5 minutes. Output goes to $DIR/momi.log. Sets MOMI_RC (124 = timed out).
momi_run() {
    MOMI_RC=0
    if command -v timeout >/dev/null 2>&1; then
        (cd "$GAMEDIR" && EXIT_ON_COMPLETE=true timeout 300 "$cli" < /dev/null > "$DIR/momi.log" 2>&1) || MOMI_RC=$?
    else
        (cd "$GAMEDIR" && EXIT_ON_COMPLETE=true "$cli" < /dev/null > "$DIR/momi.log" 2>&1) || MOMI_RC=$?
    fi
}

# The MOMI step: $1 = 1 when the mod files changed. Runs MOMI's command-line installer only if the player chose it and agrees.
momi_step() {
    if [ "$1" != 1 ]; then say 'MOMI: nothing to do (the mod files did not change).'; return 0; fi
    ran=0
    if momi_cli_ok; then
        say ''
        say "MOMI must now rebuild the game's data. MOMI's command-line installer is set up: $cli"
        say "It installs every mod in your mods folder (not only the ones ticked in the MOMI window). Close Fields of Mistria first."
        if [ "$DRY" = 1 ]; then say '[dry run] would ask whether to run it'; return 0; fi
        printf 'Run it now? [y/N] '
        ans=n; read -r ans <&3 || ans=n
        case $ans in
            y|Y|yes|YES)
                say 'Running MOMI (it can take a minute) ...'
                momi_run
                rc=$MOMI_RC
                say 'What MOMI said (last lines of '"$DIR/momi.log"'):'
                tail -n 15 "$DIR/momi.log" 2>/dev/null | sed 's/^/    /' || true
                if [ "$rc" = 0 ]; then
                    say 'MOMI finished (exit code 0). Start the game from Steam. (Exit code 0 alone does not prove every mod installed: read the lines above.)'
                    ran=1
                else
                    say "MOMI's installer did not finish well (exit code $rc)."
                fi ;;
            *) say "Not run." ;;
        esac
    fi
    if [ "$ran" != 1 ]; then
        say ''
        say 'One more step for the mod: close the game, open MOMI (Mods of Mistria installer), select MistriaMulti and click Install.'
        say 'To let this script do it next time: download MOMI'"'"'s command-line program, then run  ./install.sh --momi-cli /path/to/ModsOfMistriaInstaller-cli-linux'
    fi
}

# result file (--result): small key=value lines, replaced atomically
RES_VER=''
res() { [ -n "$RESULT" ] || return 0; printf 'state=%s\nversion=%s\nmessage=%s\nerror=%s\n' "$1" "$RES_VER" "$2" "${3:-0}" > "$RESULT.tmp" 2>/dev/null && mv -f "$RESULT.tmp" "$RESULT" 2>/dev/null || true; }
# a failure: the last thing said is the message; the exit status is the code with --result, else 1
ec() { res failed "$LASTMSG" "$1"; if [ -n "$RESULT" ]; then exit "$1"; else exit 1; fi; }

do_update() {
    if [ ! -d "$DIR" ]; then
        say "MistriaMulti is not installed here yet ($DIR is missing). Run ./install.sh first; it also sets the Steam launch option."
        ec 13
    fi
    say 'MistriaMulti update'
    if [ "$DRY" = 1 ]; then say '(dry run: nothing will be changed)'; fi
    find_steam
    find_game
    say 'Looking for the latest release on GitHub ...'
    res checking 'Looking for the latest release.'
    rc=0; fetch "$URL_LIST" "$TMP/latest.txt" 30000 10 60 || rc=$?
    if [ "$rc" = 2 ]; then say 'Neither curl nor wget is installed, so nothing can be downloaded. Nothing was changed.'; ec 20; fi
    if [ "$rc" != 0 ]; then
        say "You can also download the new MistriaMulti-<version>-Linux.tar.gz by hand from https://github.com/$REPO/releases and run its ./install.sh."
        say 'Could not reach GitHub (no network, or no release published yet). Nothing was changed.'
        ec 20
    fi
    if ! check_list "$TMP/latest.txt"; then say 'The update list is not valid, or was cut off. Nothing was changed.'; ec 21; fi
    latest=$LIST_VERSION
    RES_VER=$latest
    say "Latest release: $latest"
    res downloading 'Downloading the update.'

    # ---- mod files: download what differs, verify, assemble a complete new folder
    MODCHANGED=0 MODNOTE=''
    newmod=$TMP/newmod
    dest=''
    if [ -z "$GAMEDIR" ]; then
        MODNOTE='Game folder not found: the mod files were not updated (use MOMI with the downloaded mod folder).'
    else
        dest=$GAMEDIR/mods/mistrimulti
        have=$(installed_mod_version "$dest/manifest.toml")
        if [ -f "$dest/manifest.toml" ] && ! grep -Eq 'name = "Mistria?Multi"' "$dest/manifest.toml"; then
            MODNOTE="Another mod is in $dest: the mod files were not touched."; dest=''
        elif [ -n "$have" ] && [ "$(ver_cmp "$have" "$latest")" = 1 ]; then
            MODNOTE="The mod installed here ($have) is newer than the published $latest: the mod files were not touched."; dest=''
        fi
    fi
    if [ -n "$dest" ]; then
        mkdir -p "$newmod"
        changed=0
        while read -r hash rel; do
            mkdir -p "$newmod/$(dirname -- "$rel")"
            if [ -f "$dest/$rel" ] && [ "$(sha_of "$dest/$rel")" = "$hash" ]; then
                cp "$dest/$rel" "$newmod/$rel"
                continue
            fi
            rc=0; fetch "$(url_mod "$latest" "mod/mistrimulti/$rel")" "$newmod/$rel" 1048576 10 120 || rc=$?
            if [ "$rc" != 0 ]; then say "A download failed ($rel). Nothing was changed."; ec 22; fi
            if [ "$(sha_of "$newmod/$rel")" != "$hash" ]; then say "A downloaded file failed its checksum ($rel). Nothing was changed."; ec 22; fi
            changed=$((changed + 1))
        done < "$TMP/modfiles"
        stale=0
        if [ -d "$dest" ]; then
            cut -d' ' -f2 "$TMP/modfiles" > "$TMP/rels"
            ( cd "$dest" && find . -type f ) | sed 's|^\./||' | while read -r rel; do
                case $rel in LICENSE|CONTACT.md) continue ;; esac
                grep -qxF -- "$rel" "$TMP/rels" || echo "$rel"
            done > "$TMP/stale"
            stale=$(wc -l < "$TMP/stale" | tr -d ' ')
        fi
        if [ "$changed" -gt 0 ] || [ "$stale" -gt 0 ] || [ ! -f "$dest/manifest.toml" ]; then MODCHANGED=1; fi
        MODCOUNT=$changed MODSTALE=$stale
    fi

    # ---- programs: the Linux tar.gz named in the list, verified by hash
    PROGCHANGED=0 PROGNOTE='' PROGS=''
    if [ -s "$TMP/linuxtar" ]; then
        read -r thash tname < "$TMP/linuxtar"
        rc=0; fetch "$(url_tar "$latest" "$tname")" "$TMP/linux.tar.gz" 20971520 10 180 || rc=$?
        if [ "$rc" != 0 ]; then say "A download failed ($tname). Nothing was changed."; ec 22; fi
        if [ "$(sha_of "$TMP/linux.tar.gz")" != "$thash" ]; then say "A downloaded file failed its checksum ($tname). Nothing was changed."; ec 22; fi
        mkdir -p "$TMP/tar"
        members=''
        for b in $BINS install.sh; do members="$members MistriaMulti/$b"; done
        # shellcheck disable=SC2086
        if ! tar -xzf "$TMP/linux.tar.gz" -C "$TMP/tar" --no-same-owner $members 2>/dev/null; then
            say "The programs in $tname could not be unpacked. Nothing was changed."; ec 22
        fi
        for b in $BINS install.sh; do
            f=$TMP/tar/MistriaMulti/$b
            if [ ! -f "$f" ] || [ -L "$f" ] || [ ! -s "$f" ]; then say "$tname does not contain a usable $b. Nothing was changed."; ec 22; fi
        done
        for b in $BINS; do
            cmp -s "$TMP/tar/MistriaMulti/$b" "$DIR/$b" 2>/dev/null || { PROGS="$PROGS $b"; PROGCHANGED=$((PROGCHANGED + 1)); }
        done
    else
        PROGNOTE='This release lists no Linux programs: the programs were not changed.'
    fi

    # ---- apply (everything was downloaded and verified)
    res installing 'Installing the update.'
    if [ "$DRY" = 1 ]; then
        say "[dry run] would update the programs:${PROGS:- (none)}"
        [ -n "$dest" ] && say "[dry run] would update the mod files in $dest ($MODCOUNT changed, $MODSTALE removed)"
    else
        for b in $PROGS; do
            cp "$TMP/tar/MistriaMulti/$b" "$DIR/$b.new" && chmod 755 "$DIR/$b.new" && mv -f "$DIR/$b.new" "$DIR/$b"
        done
        if [ -s "$TMP/linuxtar" ] && ! cmp -s "$TMP/tar/MistriaMulti/install.sh" "$DIR/mistrimulti-update.sh" 2>/dev/null; then
            cp "$TMP/tar/MistriaMulti/install.sh" "$DIR/mistrimulti-update.sh.new" && chmod 755 "$DIR/mistrimulti-update.sh.new" \
                && mv -f "$DIR/mistrimulti-update.sh.new" "$DIR/mistrimulti-update.sh"
        fi
        if [ -n "$dest" ] && [ "$MODCHANGED" = 1 ]; then
            for n in LICENSE CONTACT.md; do [ -f "$dest/$n" ] && cp "$dest/$n" "$newmod/$n"; done
            mkdir -p "$GAMEDIR/mods"
            rm -rf "$dest.new" "$dest.old"
            cp -R "$newmod" "$dest.new"
            # manifest.toml last in effect: the folder is swapped as a whole, the old one kept until the new one is in place
            if [ -d "$dest" ]; then mv "$dest" "$dest.old"; fi
            if mv "$dest.new" "$dest"; then rm -rf "$dest.old"
            else [ -d "$dest.old" ] && mv "$dest.old" "$dest"; say 'Could not put the new mod files in place; the old ones were put back.'; ec 23; fi
        fi
    fi

    say ''
    say '=== Update done ==='
    say "Release $latest."
    if [ "$PROGCHANGED" -gt 0 ]; then say "Programs updated: $PROGCHANGED (in $DIR)."; elif [ -z "$PROGNOTE" ]; then say 'Programs: already up to date.'; fi
    if [ -n "$PROGNOTE" ]; then say "$PROGNOTE"; fi
    if [ -n "$MODNOTE" ]; then say "$MODNOTE"
    elif [ "$MODCHANGED" = 1 ]; then say "Mod files updated in $dest ($MODCOUNT changed, $MODSTALE old file(s) removed)."
    else say 'Mod files: already up to date.'; fi
    if [ -n "$RESULT" ]; then
        # No questions. The mod files changed (or an earlier update left the marker): MOMI has to rebuild the game's data. Its command-line
        # installer runs only when the player allowed that without a question (--momi-cli ... --always) and MISTRIMULTI_NO_MOMI is unset
        # (the caller sets it while the game is open: MOMI rewrites the game's data file). Otherwise the answer is needs_momi.
        if [ -n "$MODNOTE" ]; then res done "$MODNOTE" 0; exit 0; fi
        pend=0
        if [ "$MODCHANGED" = 1 ]; then : > "$DIR/momi-pending"; pend=1; elif [ -f "$DIR/momi-pending" ]; then pend=1; fi
        if [ "$pend" = 1 ]; then
            if [ -z "${MISTRIMULTI_NO_MOMI:-}" ] && [ -f "$DIR/momi-cli.auto" ] && momi_cli_ok; then
                res installing "Running MOMI's installer."
                momi_run
                if [ "$MOMI_RC" = 0 ]; then rm -f "$DIR/momi-pending"; res done "Updated, and MOMI installed the new mod files. Restart the game." 0; exit 0; fi
                if [ "$MOMI_RC" = 124 ]; then res needs_momi "Updated. MOMI's installer took too long; close the game and press Install in MOMI." 31; exit 0; fi
                res needs_momi "Updated, but MOMI's installer reported a problem (exit code $MOMI_RC). Close the game and press Install in MOMI." 30; exit 0
            fi
            res needs_momi 'Updated. Close the game and press Install in MOMI, then start the game.' 0
            exit 0
        fi
        if [ "$PROGCHANGED" -gt 0 ]; then res done 'Updated the MistriaMulti programs. Restart the game to use them.' 0; else res done 'MistriaMulti is up to date.' 0; fi
        exit 0
    fi
    if [ -z "$MODNOTE" ]; then
        if [ -f "$DIR/momi-pending" ] && [ "$MODCHANGED" != 1 ]; then say 'An earlier update (from the game) still needs the MOMI step.'; MODCHANGED=1; fi
        momi_step "$MODCHANGED"
        [ "$DRY" = 1 ] || rm -f "$DIR/momi-pending"
    fi
    exit 0
}

# ---------------------------------------------------------------- main
if [ -n "$DAILY" ]; then do_daily "$DAILY"; fi
if [ -n "$MOMICLI" ]; then do_momi_cli "$MOMICLI"; fi
if [ "$UPDATE" = 1 ]; then do_update; fi
if [ "$UNINSTALL" = 1 ]; then do_uninstall; exit 0; fi

say "MistriaMulti installer"; [ "$DRY" = 1 ] && say '(dry run: nothing will be changed)'

# 1. program files
have_all() { for b in $BINS; do [ -f "$1/$b" ] || return 1; done; }
PROGDIR=''
for cand in "$SRC" "$SRC/build"; do
    if have_all "$cand"; then PROGDIR=$cand; break; fi
done
# A source checkout rebuilds when it can, so old programs from an earlier build are never reused after an update.
if [ "$PROGDIR" = "$SRC/build" ] && [ -f "$SRC/scripts/build-linux.sh" ] && command -v nasm >/dev/null 2>&1 && command -v ld >/dev/null 2>&1; then
    say 'Rebuilding the programs so they match this version.'
    PROGDIR=''
fi
if [ -n "$PROGDIR" ]; then
    say "Using the program files in $PROGDIR"
else
    if [ ! -f "$SRC/scripts/build-linux.sh" ]; then
        say 'The program files (mistrimulti-launcher, -manager, -helper-linux, -steam-id-linux) are not next to install.sh'
        say 'and there is no scripts/build-linux.sh to build them. Download the mistrimulti-linux-x64 build, unpack it'
        say 'next to install.sh (or into a build folder), and run ./install.sh again.'
        exit 1
    fi
    missing=''
    command -v nasm >/dev/null 2>&1 || missing="$missing nasm"
    command -v ld >/dev/null 2>&1 || missing="$missing binutils"
    if [ -n "$missing" ]; then
        APT='sudo apt-get install -y nasm binutils'
        if [ "$YES" = 1 ] && [ "$DRY" != 1 ] && command -v apt-get >/dev/null 2>&1; then
            say "Installing the build tools: $APT"
            $APT
        else
            say 'To build the programs you need the build tools. Run this one command, then run ./install.sh again:'
            say ''
            say "    $APT"
            say ''
            say '(or run ./install.sh --yes and it will run that command for you; on SteamOS see docs/STEAM-DECK.md)'
            [ "$DRY" = 1 ] && say '[dry run] would then build with scripts/build-linux.sh'
            [ "$DRY" = 1 ] || exit 1
        fi
    fi
    act 'build the programs: sh scripts/build-linux.sh'
    if [ "$DRY" != 1 ]; then
        sh "$SRC/scripts/build-linux.sh" > "$TMP/build.log" 2>&1 || { cat "$TMP/build.log"; say 'The build failed (see above).'; exit 1; }
        PROGDIR=$SRC/build
        have_all "$PROGDIR" || { say 'The build finished but some programs are missing.'; exit 1; }
    fi
fi

# 2. copy into one folder
act "copy the four programs into $DIR"
if [ "$DRY" != 1 ]; then
    mkdir -p "$DIR"
    for b in $BINS; do
        if [ -f "$DIR/$b" ] && cmp -s "$PROGDIR/$b" "$DIR/$b"; then chmod 755 "$DIR/$b"; continue; fi
        cp "$PROGDIR/$b" "$DIR/$b.new" && chmod 755 "$DIR/$b.new" && mv -f "$DIR/$b.new" "$DIR/$b"
    done
    # the update script the manager, the launcher (daily check) and the game's Update button run
    if ! cmp -s "$SELF" "$DIR/mistrimulti-update.sh" 2>/dev/null; then
        cp "$SELF" "$DIR/mistrimulti-update.sh.new" && chmod 755 "$DIR/mistrimulti-update.sh.new" && mv -f "$DIR/mistrimulti-update.sh.new" "$DIR/mistrimulti-update.sh"
    fi
fi
note "Programs are in $DIR"
link=$HOME/.local/bin/mistrimulti
if [ -d "$HOME/.local/bin" ]; then
    if [ ! -e "$link" ] || [ -L "$link" ]; then
        act "link $link to the manager (so 'mistrimulti host' / 'mistrimulti join' work if ~/.local/bin is on your PATH)"
        [ "$DRY" = 1 ] || ln -sf "$DIR/mistrimulti-manager" "$link"
    fi
fi

# 3. Steam launch option
find_steam
find_game
printf '%s\n' "$APPID" > "$TMP/appid"
MANUAL=0 EDITED=0
if [ ! -s "$TMP/roots" ]; then
    say 'Steam was not found (looked in ~/.steam/steam, ~/.steam/debian-installation, ~/.local/share/Steam and the Flatpak folder).'
    note 'Steam not found; set the launch option by hand.'
    MANUAL=1
elif [ "$FOUND_MANIFEST" = 0 ]; then
    say "Fields of Mistria is not installed in any Steam library I could find (no appmanifest). Install it in Steam first,"
    say 'then run ./install.sh again; the launch option is not touched until then.'
    note 'Game not found in Steam; launch option NOT set.'
    MANUAL=1
elif steam_running; then
    say 'Steam is running, so its settings are not edited (Steam would overwrite them when it closes).'
    note 'Steam is running: launch option NOT set. Close Steam completely and run ./install.sh again.'
    MANUAL=1
else
    say "Setting the Steam launch option for Fields of Mistria (app $APPID):"
    n=0
    while IFS= read -r root; do
        for f in "$root"/userdata/*/config/localconfig.vdf; do
            [ -f "$f" ] || continue
            case $f in */userdata/0/*) continue ;; esac
            n=$((n + 1)); apply_launch_option "$f"
        done
    done < "$TMP/roots"
    if [ "$n" = 0 ]; then
        say '  No Steam user settings (userdata/*/config/localconfig.vdf) found. Start Steam and log in once, then run this again.'
        note 'No Steam user found; launch option NOT set.'
        MANUAL=1
    elif [ "$EDITED" -gt 0 ]; then note "Steam launch option set for $EDITED Steam user(s); original settings backed up (*$BACKUP_SUFFIX)."; fi
fi

# 4. the mod
MODSRC=$SRC/mod/mistrimulti
MODDONE=0
if [ ! -d "$MODSRC" ]; then
    note 'No mod folder next to install.sh; install the mod with MOMI.'
elif [ -z "$GAMEDIR" ]; then
    note 'Game folder not found; install the mod with MOMI (below).'
else
    dest=$GAMEDIR/mods/mistrimulti
    if [ -f "$dest/manifest.toml" ] && ! grep -Eq 'name = "Mistria?Multi"' "$dest/manifest.toml"; then
        say "Another mod already occupies $dest; not touched."
        note "Mod NOT copied: another mod is in $dest."
    else
        act "copy the mod to $dest"
        if [ "$DRY" != 1 ]; then
            mkdir -p "$GAMEDIR/mods"
            rm -rf "$dest.new"; cp -R "$MODSRC" "$dest.new"
            for n in LICENSE CONTACT.md; do [ -f "$SRC/$n" ] && cp "$SRC/$n" "$dest.new/"; done
            rm -rf "$dest"; mv "$dest.new" "$dest"
        fi
        MODDONE=1
        note "Mod files copied to $dest"
    fi
fi

# 5. summary
say ''
say '=== Done ==='
cat "$SUMMARY"
if [ "$MANUAL" = 1 ]; then
    say ''
    say 'Steam launch option to set by hand (Steam > right-click Fields of Mistria > Properties > Launch Options):'
    say "    $LAUNCH_LINE"
fi
if [ "$MODDONE" = 1 ]; then
    say ''
    say 'One more step for the mod: open MOMI (Mods of Mistria installer), select MistriaMulti and click Install.'
    say 'No MOMI yet? Get it here: https://github.com/Garethp/Mods-of-Mistria-Installer/releases'
else
    say ''
    say "To install the mod: open MOMI (Mods of Mistria installer), add the folder $SRC/mod/mistrimulti, and click Install."
    say 'No MOMI yet? Get it here: https://github.com/Garethp/Mods-of-Mistria-Installer/releases'
fi
say ''
say 'That is all the setup. Start Fields of Mistria from Steam (press Play), choose New Game or Load Game, then Multiplayer:'
say '  - Host a game  shows the addresses to give your friends (Tailscale or this network), then starts your world.'
say '  - Join a game  looks for hosts (or type an address), asks for a password if the host set one, downloads the'
say '                 host'"'"'s world and enters it.'
say 'The badge at the bottom right says Multiplayer: Idle / Online / Offline, with the reason when it is Offline.'
say "(Advanced and optional: $DIR/mistrimulti-manager host|join pre-sets a role that starts without the menu.)"
exit 0
