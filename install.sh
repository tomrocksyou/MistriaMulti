#!/bin/sh
# MistriaMulti installer for Linux (Debian/Ubuntu, Steam Deck desktop mode).  Run it once:   ./install.sh
# After that you only start the game from Steam: hosting and joining are chosen in the game's own Multiplayer menu.
#
#   ./install.sh               install (safe to run again)
#   ./install.sh --dry-run     show what would be done, change nothing
#   ./install.sh --uninstall   put Steam's settings back and remove the program folder
#   ./install.sh --yes         allow it to run the one `sudo apt-get install` it may need (nasm, binutils)
#
# Environment: MISTRIMULTI_DIR (program folder, default ~/.local/share/mistrimulti),
#              MISTRIMULTI_APPID (Steam app id, default: found from the game's appmanifest, else 2142790),
#              MISTRIMULTI_STEAM_RUNNING=1|0 (override the "is Steam running" check).
set -eu

exec 3<&0
SRC=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEFAULT_APPID=2142790          # Fields of Mistria; also the compatdata id used in tests/test_launcher_linux.py
GAME_NAME='Fields of Mistria'
DIR=${MISTRIMULTI_DIR:-$HOME/.local/share/mistrimulti}
BINS='mistrimulti-launcher mistrimulti-manager mistrimulti-helper-linux mistrimulti-steam-id-linux'
BACKUP_SUFFIX=.mistrimulti-backup
APPLIED_SUFFIX=.mistrimulti-applied

DRY=0 YES=0 UNINSTALL=0
for arg in "$@"; do
    case $arg in
        --dry-run) DRY=1 ;;
        --yes|-y) YES=1 ;;
        --uninstall) UNINSTALL=1 ;;
        -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $arg (try --help)" >&2; exit 2 ;;
    esac
done

TMP=$(mktemp -d "${TMPDIR:-/tmp}/mistrimulti-install.XXXXXX")
trap 'rm -rf "$TMP"' EXIT INT TERM

say() { printf '%s\n' "$*"; }
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

# ---------------------------------------------------------------- main
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
