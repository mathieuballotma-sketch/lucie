.PHONY: help demo test clean \
        version-check dmg-build dmg-unsigned dmg-signed \
        dmg-check-secrets dmg-test-install dmg-clean

# ====== Targets vitrine ======

help:
	@echo "Beaume — public showcase targets"
	@echo ""
	@echo "  make demo               Run the truth rule demonstration"
	@echo "  make test               Run the public test suite"
	@echo "  make clean              Remove Python caches and build artifacts"
	@echo ""
	@echo "Beaume — packaging macOS targets (Sprint 0.5.0)"
	@echo ""
	@echo "  make version-check      Verify version 0.5.0 is consistent across files"
	@echo "  make dmg-build          Build dist/Beaume.app via py2app (no sign)"
	@echo "  make dmg-unsigned       Build full DMG without signature (local test)"
	@echo "  make dmg-signed         Build + sign + notarize + DMG (requires Apple creds)"
	@echo "  make dmg-check-secrets  Negative grep secrets/cloud SDKs in bundle"
	@echo "  make dmg-test-install   Run scripts/test_install.sh on dist/Beaume.dmg"
	@echo "  make dmg-clean          Remove dist/ and build/ artifacts"

demo:
	@python examples/truth_rule_proof.py

test:
	@python -m pytest tests/ -v

clean:
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "Cleaned."

# ====== Packaging macOS ======

# Source of truth = pyproject.toml. All other files must align.
EXPECTED_VERSION := $(shell grep '^version' pyproject.toml | head -1 | sed 's/.*"\(.*\)".*/\1/')

version-check:
	@echo "[1/4] Expected version (pyproject.toml): $(EXPECTED_VERSION)"
	@v_setup=$$(grep 'version=' packaging/setup_py2app.py | head -1 | sed 's/.*"\(.*\)".*/\1/'); \
	echo "[2/4] packaging/setup_py2app.py: $$v_setup"; \
	[ "$$v_setup" = "$(EXPECTED_VERSION)" ] || { echo "❌ setup_py2app.py mismatch"; exit 1; }
	@v_short=$$(grep -A1 'CFBundleShortVersionString' packaging/Info.plist | tail -1 | sed 's/.*<string>\(.*\)<\/string>.*/\1/'); \
	echo "[3/4] packaging/Info.plist CFBundleShortVersionString: $$v_short"; \
	[ "$$v_short" = "$(EXPECTED_VERSION)" ] || { echo "❌ Info.plist mismatch"; exit 1; }
	@v_bundle=$$(grep -A1 'CFBundleVersion' packaging/Info.plist | tail -1 | sed 's/.*<string>\(.*\)<\/string>.*/\1/'); \
	echo "[4/4] packaging/Info.plist CFBundleVersion: $$v_bundle"; \
	[ "$$v_bundle" = "$(EXPECTED_VERSION)" ] || { echo "❌ Info.plist CFBundleVersion mismatch"; exit 1; }
	@echo "✅ All versions aligned to $(EXPECTED_VERSION)"

dmg-build:
	@echo "[build] py2app → dist/Beaume.app"
	@bash packaging/build.sh

dmg-unsigned:
	@echo "[unsigned] Building DMG without signature (local test only)"
	@FORCE_UNSIGNED=1 bash packaging/release.sh

dmg-signed:
	@echo "[signed] Building DMG with sign + notarize (requires Apple creds)"
	@if [ -z "$$DEVELOPER_ID" ] || [ -z "$$APPLE_ID" ] || [ -z "$$APPLE_TEAM_ID" ] || [ -z "$$APPLE_APP_PWD" ]; then \
	    echo "❌ Missing Apple credentials. Required env vars:"; \
	    echo "    DEVELOPER_ID, APPLE_ID, APPLE_TEAM_ID, APPLE_APP_PWD"; \
	    echo "    See docs/PACKAGING_GUIDE.md for setup."; \
	    exit 1; \
	fi
	@bash packaging/release.sh

dmg-check-secrets:
	@bash scripts/check_no_cloud_sdks.sh

dmg-test-install:
	@bash scripts/test_install.sh

dmg-clean:
	@rm -rf dist/ build/
	@echo "✅ Removed dist/ and build/"
