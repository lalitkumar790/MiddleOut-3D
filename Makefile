.PHONY: install fixtures test benchmark
install:
	python -m pip install -r requirements.txt
fixtures:
	python -m middleout3d generate-fixtures --out samples
test:
	python -m unittest discover -s tests -v
benchmark: fixtures
	python -m middleout3d benchmark samples --out results/baseline.json --bits 16 --repeats 5
