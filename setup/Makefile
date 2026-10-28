# The safe commands for setup/, in the order you run them. Each says what to do next.
# This file holds no logic of its own: it fixes the order, so a saved plan is always the plan that
# runs. Runs on macOS's stock GNU Make 3.81. Clumio credentials: CLUMIO_API_TOKEN, CLUMIO_API_BASE_URL.
#
#   make preflight    read-only: tools, settings, AWS sign-in, Clumio token, unit, Region, rule slots
#   make preview      read-only: every IAM role Clumio gets, and whether the deploy role may create it
#                     (make preview DEPLOY_ROLE=<role ARN> checks that role instead of your sign-in)
#   make plan         saves a plan of your settings, shows it, then what it will protect, by tag.
#                     It doesn't keep a plan that shortens a PITR window, unless the profile allows it.
#   make apply        applies the saved plan, checks the result, then runs make status
#   make status       read-only: who protects each tagged resource, and its last backup
#   make teardown     checks nothing is running, then saves a plan that removes everything this
#                     folder created. Production refuses. Then make apply.

SHELL := /bin/bash
.PHONY: help preflight preview plan apply status teardown

help:
	@sed -n '5,14p' Makefile | sed 's/^# //'

preflight:
	@./status.py --preflight

preview:
	@./preview/preview.sh $(if $(DEPLOY_ROLE),--as $(DEPLOY_ROLE))

plan:
	@rm -f tfplan teardown.tfplan
	@terraform init -input=false -lockfile=readonly > /dev/null
	@terraform plan -input=false -out=tfplan
	@echo
	@./status.py --preview || { rm -f tfplan; echo; echo "The plan was not kept: the preview above says why. Fix that, then run make plan again."; exit 1; }
	@echo
	@echo "Next: read the plan, and what it protects. If both are what you expect, run: make apply"

status:
	@./status.py

# status.py refuses in production, and while Clumio is still backing up these resources: removing
# protection mid-backup leaves its tasks stuck. The guard in Terraform refuses production as well.
teardown:
	@rm -f tfplan teardown.tfplan
	@./status.py --teardown
	@terraform init -input=false -lockfile=readonly > /dev/null
	@terraform plan -destroy -input=false -out=teardown.tfplan
	@echo
	@echo "Next: read the plan above. To remove all of it, run: make apply"

# A saved plan, or nothing: an apply never decides on its own what to change.
apply:
	@if [ -f teardown.tfplan ]; then \
	  terraform apply -input=false teardown.tfplan; result=$$?; rm -f teardown.tfplan; [ $$result -eq 0 ] || exit $$result; \
	  echo; left="$$(terraform state list | grep -v '^data\.' | grep -v '\.data\.' || true)"; \
	  if [ -z "$$left" ]; then echo "PASS  Everything this folder created is gone. Backups Clumio already made stay until their retention ends."; \
	  else echo "FAIL  Still in Terraform's state:"; echo "$$left" | sed 's/^/        /'; exit 1; fi; \
	elif [ -f tfplan ]; then \
	  terraform apply -input=false tfplan; result=$$?; rm -f tfplan; [ $$result -eq 0 ] || exit $$result; \
	  echo; echo "Checking that a new plan shows no changes..."; \
	  terraform plan -input=false -detailed-exitcode > /dev/null; result=$$?; \
	  if [ $$result -eq 0 ]; then echo "PASS  No changes: Clumio and AWS match your settings."; echo; ./status.py; \
	  elif [ $$result -eq 2 ]; then echo "FAIL  A new plan still shows changes. An interrupted apply can need a second pass: run make plan, read it, make apply."; exit 1; \
	  else echo "FAIL  The check plan failed. Run make plan to see why."; exit 1; fi; \
	else \
	  echo "No saved plan. Run make plan (or make teardown) first, and read it."; exit 1; \
	fi
