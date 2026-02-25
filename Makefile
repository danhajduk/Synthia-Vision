.PHONY: step finalize rebuild

step:
	@./scripts/task.sh step -m "$(msg)"

finalize:
	@./scripts/task.sh finalize -m "$(msg)"

rebuild:
	@./scripts/rebuild.sh