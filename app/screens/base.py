class Screen:
    name = "screen"
    accent = (255, 255, 255)
    poll_keys = ()
    sources = ()  # which network feeds this screen needs; only these are polled while active

    def __init__(self, ctx):
        self.ctx = ctx

    def enter(self):
        pass

    def leave(self):
        pass

    def on_pad(self, key):
        return None

    def on_touch(self, x, y):
        return None

    def draw(self):
        raise NotImplementedError
