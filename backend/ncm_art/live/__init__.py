"""Synchronous inference for the instrument.

The writing desk's job queue exists for work that takes seconds or minutes.
On this machine a TinyStories trace or one variation takes well under a
second, so the instrument calls the model directly from the API process and
keeps nothing until the artist asks.
"""
