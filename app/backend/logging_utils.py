"""Do not put invitation/reset/CSRF query tokens into ASGI logs."""
import logging

class RedactQuery(logging.Filter):
    def filter(self,record):
        if isinstance(record.args,tuple):
            record.args=tuple(value.split('?',1)[0] if isinstance(value,str) and value.startswith('/') else value for value in record.args)
        return True

for name in ('uvicorn.access','uvicorn.error'):
    logging.getLogger(name).addFilter(RedactQuery())
