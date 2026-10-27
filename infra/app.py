#!/usr/bin/env python3
from canaco_infra.app_factory import create_app

app = create_app()
app.synth()
