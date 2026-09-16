#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# install_macos_quick_action.sh
# Installs a macOS Finder Quick Action (right-click → Quick Actions) that
# launches the ImgCrunch wizard on the selected files and folders.
#
# The action calls a small launcher in ~/Library/Application Support/ImgCrunch,
# which starts the `imgcrunch` command when it is installed (pipx) and this
# clone's resize.sh otherwise. Moving the clone therefore only breaks the
# action in the second case, and then the launcher says so.
#
# Usage:  bash install_macos_quick_action.sh
# Requires: macOS with Automator / Quick Actions support
#
# For tests: IMGCRUNCH_SERVICES_DIR and IMGCRUNCH_SUPPORT_DIR redirect where
# things are written, and IMGCRUNCH_SKIP_REFRESH=1 skips the services refresh.
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKFLOW_NAME="ImgCrunch"
SERVICES_DIR="${IMGCRUNCH_SERVICES_DIR:-$HOME/Library/Services}"
SUPPORT_DIR="${IMGCRUNCH_SUPPORT_DIR:-$HOME/Library/Application Support/ImgCrunch}"
WORKFLOW_DIR="$SERVICES_DIR/${WORKFLOW_NAME}.workflow"
CONTENTS_DIR="$WORKFLOW_DIR/Contents"
LAUNCHER="$SUPPORT_DIR/launch.sh"

echo ""
echo "🖼️  ImgCrunch — macOS Quick Action Installer"
echo "─────────────────────────────────────────────────"
echo ""

# Verify we're on macOS
if [[ "$(uname)" != "Darwin" ]]; then
    echo "❌  This script only works on macOS."
    exit 1
fi

# What the action should start. An `imgcrunch` found inside this clone (the
# venv's editable install) does not count: it would tie the action to the
# clone's location just like resize.sh does, without the venv check.
TARGET=""
if CANDIDATE="$(command -v imgcrunch 2>/dev/null)"; then
    CANDIDATE_REAL="$(cd "$(dirname "$CANDIDATE")" && pwd -P)/$(basename "$CANDIDATE")"
    if [[ "$CANDIDATE_REAL" != "$(cd "$SCRIPT_DIR" && pwd -P)/"* ]]; then
        TARGET="$CANDIDATE"
        TARGET_KIND="the installed imgcrunch command"
    fi
fi
if [[ -z "$TARGET" ]]; then
    if [[ ! -f "$SCRIPT_DIR/resize.sh" ]]; then
        echo "❌  No imgcrunch command on PATH and no resize.sh in $SCRIPT_DIR"
        exit 1
    fi
    TARGET="$SCRIPT_DIR/resize.sh"
    TARGET_KIND="resize.sh in this clone"
fi

# The launcher path ends up inside AppleScript, inside a shell string, inside
# XML. Refuse the few characters that would need escaping at every layer.
case "$LAUNCHER" in
    *[\'\"\\\&\<\>]*)
        echo "❌  Cannot install into a path containing quotes, backslashes, & < or >:"
        echo "    $LAUNCHER"
        exit 1 ;;
esac

# ── Launcher ─────────────────────────────────────────────────────────────────
mkdir -p "$SUPPORT_DIR"
{
    echo '#!/bin/bash'
    echo '# Written by install_macos_quick_action.sh; the Finder Quick Action runs this.'
    printf 'TARGET=%q\n' "$TARGET"
    cat << 'LAUNCH_EOF'
if [[ ! -f "$TARGET" ]]; then
    echo "ImgCrunch is no longer at:"
    echo "  $TARGET"
    echo ""
    echo "It was moved or uninstalled. Run install_macos_quick_action.sh again"
    echo "from wherever ImgCrunch lives now."
    exit 1
fi
if [[ "$TARGET" == *.sh ]]; then
    exec bash "$TARGET" "$@"
fi
exec "$TARGET" "$@"
LAUNCH_EOF
} > "$LAUNCHER"
chmod +x "$LAUNCHER"

# Remove old workflow if present
if [[ -d "$WORKFLOW_DIR" ]]; then
    echo "♻️  Removing existing workflow..."
    rm -rf "$WORKFLOW_DIR"
fi

# Create workflow bundle structure
mkdir -p "$CONTENTS_DIR"

# ── Info.plist ───────────────────────────────────────────────────────────────
cat > "$CONTENTS_DIR/Info.plist" << 'PLIST_EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>NSServices</key>
	<array>
		<dict>
			<key>NSBackgroundColorName</key>
			<string>background</string>
			<key>NSIconName</key>
			<string>NSActionTemplate</string>
			<key>NSMenuItem</key>
			<dict>
				<key>default</key>
				<string>ImgCrunch</string>
			</dict>
			<key>NSMessage</key>
			<string>runWorkflowAsService</string>
			<key>NSRequiredContext</key>
			<dict>
				<key>NSApplicationIdentifier</key>
				<string>com.apple.finder</string>
			</dict>
			<key>NSSendFileTypes</key>
			<array>
				<string>public.item</string>
			</array>
		</dict>
	</array>
</dict>
</plist>
PLIST_EOF

# ── document.wflow ──────────────────────────────────────────────────────────
# Automator workflow XML that runs a shell script to open Terminal with the
# selection written to a per-user temp file for the launcher
cat > "$CONTENTS_DIR/document.wflow" << WFLOW_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>AMApplicationBuild</key>
	<string>523</string>
	<key>AMApplicationVersion</key>
	<string>2.10</string>
	<key>AMDocumentVersion</key>
	<string>2</string>
	<key>actions</key>
	<array>
		<dict>
			<key>action</key>
			<dict>
				<key>AMAccepts</key>
				<dict>
					<key>Container</key>
					<string>List</string>
					<key>Optional</key>
					<false/>
					<key>Types</key>
					<array>
						<string>com.apple.cocoa.string</string>
					</array>
				</dict>
				<key>AMActionVersion</key>
				<string>2.0.3</string>
				<key>AMApplication</key>
				<array>
					<string>Automator</string>
				</array>
				<key>AMParameterProperties</key>
				<dict>
					<key>COMMAND_STRING</key>
					<dict/>
					<key>CheckedForUserDefaultShell</key>
					<dict/>
					<key>inputMethod</key>
					<dict/>
					<key>shell</key>
					<dict/>
					<key>source</key>
					<dict/>
				</dict>
				<key>AMProvides</key>
				<dict>
					<key>Container</key>
					<string>List</string>
					<key>Types</key>
					<array>
						<string>com.apple.cocoa.string</string>
					</array>
				</dict>
				<key>ActionBundlePath</key>
				<string>/System/Library/Automator/Run Shell Script.action</string>
				<key>ActionName</key>
				<string>Run Shell Script</string>
				<key>ActionParameters</key>
				<dict>
					<key>COMMAND_STRING</key>
					<string>ARGS_FILE=\$(mktemp -t imgcrunch_args)
for f in "\$@"; do
	echo "\$f" >> "\$ARGS_FILE"
done
osascript -e "tell application \"Terminal\"" -e "activate" -e "do script \"'${LAUNCHER}' --wizard --args-file '\$ARGS_FILE'\"" -e "end tell"</string>
					<key>CheckedForUserDefaultShell</key>
					<true/>
					<key>inputMethod</key>
					<integer>1</integer>
					<key>shell</key>
					<string>/bin/bash</string>
					<key>source</key>
					<string></string>
				</dict>
				<key>BundleIdentifier</key>
				<string>com.apple.RunShellScript</string>
				<key>CFBundleVersion</key>
				<string>2.0.3</string>
				<key>CanShowSelectedItemsWhenRun</key>
				<false/>
				<key>CanShowWhenRun</key>
				<true/>
				<key>Category</key>
				<array>
					<string>AMCategoryUtilities</string>
				</array>
				<key>Class Name</key>
				<string>RunShellScriptAction</string>
				<key>InputUUID</key>
				<string>B1B2C3D4-E5F6-7890-ABCD-EF1234567891</string>
				<key>Keywords</key>
				<array>
					<string>Shell</string>
					<string>Script</string>
					<string>Command</string>
					<string>Run</string>
					<string>Unix</string>
				</array>
				<key>OutputUUID</key>
				<string>B1B2C3D4-E5F6-7890-ABCD-EF1234567892</string>
				<key>UUID</key>
				<string>B1B2C3D4-E5F6-7890-ABCD-EF1234567890</string>
				<key>UnlocalizedApplications</key>
				<array>
					<string>Automator</string>
				</array>
				<key>arguments</key>
				<dict>
					<key>0</key>
					<dict>
						<key>default value</key>
						<integer>1</integer>
						<key>name</key>
						<string>inputMethod</string>
						<key>required</key>
						<string>0</string>
						<key>type</key>
						<string>0</string>
						<key>uuid</key>
						<string>0</string>
					</dict>
					<key>1</key>
					<dict>
						<key>default value</key>
						<false/>
						<key>name</key>
						<string>CheckedForUserDefaultShell</string>
						<key>required</key>
						<string>0</string>
						<key>type</key>
						<string>0</string>
						<key>uuid</key>
						<string>1</string>
					</dict>
					<key>2</key>
					<dict>
						<key>default value</key>
						<string></string>
						<key>name</key>
						<string>source</string>
						<key>required</key>
						<string>0</string>
						<key>type</key>
						<string>0</string>
						<key>uuid</key>
						<string>2</string>
					</dict>
					<key>3</key>
					<dict>
						<key>default value</key>
						<string></string>
						<key>name</key>
						<string>COMMAND_STRING</string>
						<key>required</key>
						<string>0</string>
						<key>type</key>
						<string>0</string>
						<key>uuid</key>
						<string>3</string>
					</dict>
					<key>4</key>
					<dict>
						<key>default value</key>
						<string>/bin/sh</string>
						<key>name</key>
						<string>shell</string>
						<key>required</key>
						<string>0</string>
						<key>type</key>
						<string>0</string>
						<key>uuid</key>
						<string>4</string>
					</dict>
				</dict>
				<key>isViewVisible</key>
				<integer>1</integer>
				<key>location</key>
				<string>309.000000:305.000000</string>
				<key>nibPath</key>
				<string>/System/Library/Automator/Run Shell Script.action/Contents/Resources/Base.lproj/main.nib</string>
			</dict>
			<key>isViewVisible</key>
			<integer>1</integer>
		</dict>
	</array>
	<key>connectors</key>
	<dict/>
	<key>workflowMetaData</key>
	<dict>
		<key>applicationBundleID</key>
		<string>com.apple.finder</string>
		<key>applicationBundleIDsByPath</key>
		<dict>
			<key>/System/Library/CoreServices/Finder.app</key>
			<string>com.apple.finder</string>
		</dict>
		<key>applicationPath</key>
		<string>/System/Library/CoreServices/Finder.app</string>
		<key>applicationPaths</key>
		<array>
			<string>/System/Library/CoreServices/Finder.app</string>
		</array>
		<key>inputTypeIdentifier</key>
		<string>com.apple.Automator.fileSystemObject</string>
		<key>outputTypeIdentifier</key>
		<string>com.apple.Automator.nothing</string>
		<key>presentationMode</key>
		<integer>15</integer>
		<key>processesInput</key>
		<false/>
		<key>serviceApplicationBundleID</key>
		<string>com.apple.finder</string>
		<key>serviceApplicationPath</key>
		<string>/System/Library/CoreServices/Finder.app</string>
		<key>serviceInputTypeIdentifier</key>
		<string>com.apple.Automator.fileSystemObject</string>
		<key>serviceOutputTypeIdentifier</key>
		<string>com.apple.Automator.nothing</string>
		<key>serviceProcessesInput</key>
		<false/>
		<key>systemImageName</key>
		<string>NSActionTemplate</string>
		<key>useAutomaticInputType</key>
		<false/>
		<key>workflowTypeIdentifier</key>
		<string>com.apple.Automator.servicesMenu</string>
	</dict>
</dict>
</plist>
WFLOW_EOF

# Refresh the Services menu. This used to run `lsregister -kill -r`, which
# resets the whole LaunchServices database; pbs -update rebuilds only services.
if [[ -z "${IMGCRUNCH_SKIP_REFRESH:-}" ]]; then
    /System/Library/CoreServices/pbs -update 2>/dev/null || true
fi

echo "✅  Quick Action installed to:"
echo "    $WORKFLOW_DIR"
echo ""
echo "▶️  It starts $TARGET_KIND:"
echo "    $TARGET"
if [[ "$TARGET" == */resize.sh ]]; then
    echo "    Moving this clone breaks the action; run this installer again afterwards,"
    echo "    or install the command with pipx and re-run it to be independent of the clone."
fi
echo ""
echo "📂  How to use:"
echo "    1. Open Finder"
echo "    2. Right-click any folder"
echo "    3. Quick Actions → \"${WORKFLOW_NAME}\""
echo ""
echo "🗑️  To uninstall, delete:"
echo "    $WORKFLOW_DIR"
echo "    $SUPPORT_DIR"
echo ""
