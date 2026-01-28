PYTHONPATH=src

.PHONY: install run graph

install:
	python3 -m venv .venv
	. .venv/bin/activate && pip install -r requirements.txt

run:
	. .venv/bin/activate && PYTHONPATH=$(PYTHONPATH) python src/main.py

graph:
	. .venv/bin/activate && PYTHONPATH=$(PYTHONPATH) python src/graph.py
