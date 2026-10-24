PYTHON ?= python3
TV ?= YOUR_TV_IP
.PHONY: build install app home privacy status home-off privacy-off off test preview
build:
	$(PYTHON) scripts/build.py
install:
	$(PYTHON) scripts/tv.py install --host $(TV)
app:
	$(PYTHON) scripts/tv.py app --host $(TV)
home:
	$(PYTHON) scripts/tv.py home --host $(TV)
privacy:
	$(PYTHON) scripts/tv.py privacy --host $(TV)
status:
	$(PYTHON) scripts/tv.py status --host $(TV)
home-off:
	$(PYTHON) scripts/tv.py home-off --host $(TV)
privacy-off:
	$(PYTHON) scripts/tv.py privacy-off --host $(TV)
off:
	$(PYTHON) scripts/tv.py off --host $(TV)
test:
	node --test tests/*.test.cjs fullhome-integration/tests/*.test.cjs
	$(PYTHON) -m unittest discover -s tests -v
	$(PYTHON) -m unittest discover -s fullhome-integration/tests -v
preview:
	$(PYTHON) -m http.server 8080 --bind 127.0.0.1
