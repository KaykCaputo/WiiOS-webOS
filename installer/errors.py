class InstallerError(Exception):
    def __init__(self, code, message, exit_code=5):
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code

    def result(self):
        return {'ok': False, 'reasonCode': self.code, 'message': str(self)}
