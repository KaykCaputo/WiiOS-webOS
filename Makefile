PYTHON ?= python3
TV ?= YOUR_TV_IP
INSTALLER_ARGS ?=
.PHONY: build install app home privacy status home-off privacy-off off test preview
build:
	$(PYTHON) scripts/build.py
install:
	$(PYTHON) scripts/tv.py install --host $(TV) $(INSTALLER_ARGS)
app:
	$(PYTHON) scripts/tv.py app --host $(TV) $(INSTALLER_ARGS)
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
	npm test
preview:
	$(PYTHON) -m http.server 8080 --bind 127.0.0.1
