from rich import print as rprint

def log_step(step: str, **kwargs):
    rprint({ "step": step, **kwargs })
