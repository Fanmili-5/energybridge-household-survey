from common import digest
from executable import commands
def command_signature(plan):return digest(commands(plan))
