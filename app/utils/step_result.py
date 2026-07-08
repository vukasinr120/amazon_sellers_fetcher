class StepResult:
    def __init__(self, row_count=None, marketplace_results=None):
        self.row_count = row_count
        self.marketplace_results = marketplace_results or []
