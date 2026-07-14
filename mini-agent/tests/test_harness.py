"""End-to-end harness test with a scripted provider (no network, no mocks
of our own code -- only the network boundary is faked)."""

import asyncio
import os
import tempfile
import unittest

from miniagent import LocalSession, Rule, ScriptedProvider
from miniagent.types import Finish, TextDelta, ToolCallRequest


class HarnessTest(unittest.TestCase):
    def test_full_loop_with_tool_call(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            provider = ScriptedProvider(turns=[
                [
                    TextDelta(text="Creating the file."),
                    ToolCallRequest(call_id="c1", tool="write",
                                    args={"path": "hello.txt", "content": "hi\n"}),
                    Finish(reason="tool_calls"),
                ],
                [
                    TextDelta(text="Done, hello.txt created."),
                    Finish(reason="stop", usage={"input_tokens": 10, "output_tokens": 5}),
                ],
            ])
            session = LocalSession(
                provider=provider,
                workdir=workdir,
                rules=[Rule(action="write", pattern="*", decision="allow")],
            )
            final = asyncio.run(session.prompt("create hello.txt"))

            # Loop terminated on the right message and side effect happened.
            self.assertEqual(final.finish_reason, "stop")
            self.assertIn("Done", final.text())
            with open(os.path.join(workdir, "hello.txt")) as f:
                self.assertEqual(f.read(), "hi\n")

            # Transcript: user, assistant(tool), assistant(final).
            history = session.store.history(session.id)
            self.assertEqual([m.role for m in history], ["user", "assistant", "assistant"])
            call = history[1].tool_calls()[0]
            self.assertEqual(call.status, "completed")
            self.assertIn("hello.txt", call.output)

            # Second model call saw the tool result in its history.
            self.assertEqual(len(provider.calls), 2)
            self.assertEqual(provider.calls[1].messages[1].tool_calls()[0].status, "completed")

            # Trace captured the run.
            types = [e.type for e in session.trace.read(session.id)]
            self.assertIn("tool.finished", types)
            self.assertIn("session.idle", types)

    def test_permission_denial_becomes_tool_error(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            provider = ScriptedProvider(turns=[
                [
                    ToolCallRequest(call_id="c1", tool="bash", args={"command": "rm -rf /"}),
                    Finish(reason="tool_calls"),
                ],
                [
                    TextDelta(text="Understood, I will not run that."),
                    Finish(reason="stop"),
                ],
            ])
            session = LocalSession(
                provider=provider,
                workdir=workdir,
                rules=[Rule(action="bash", pattern="rm *", decision="deny")],
            )
            final = asyncio.run(session.prompt("wipe the disk"))

            self.assertEqual(final.finish_reason, "stop")
            call = session.store.history(session.id)[1].tool_calls()[0]
            self.assertEqual(call.status, "error")
            self.assertIn("Permission denied", call.error)


if __name__ == "__main__":
    unittest.main()
