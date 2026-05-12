.PHONY: help demo test clean

help:
	@echo "Lucie — public showcase targets"
	@echo ""
	@echo "  make demo    Run the truth rule demonstration"
	@echo "  make test    Run the public test suite"
	@echo "  make clean   Remove Python caches and build artifacts"

demo:
	@python examples/truth_rule_proof.py

test:
	@python -m pytest tests/ -v

clean:
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "Cleaned."
