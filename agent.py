from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent, AgentSession
from livekit.plugins import gradium, google, aicoustics, silero

load_dotenv()

class ClaimsAgent(Agent):
    def __init__(self):
        with open("prompts/system.md") as f:
            instructions = f.read()
        super().__init__(instructions=instructions)

async def entrypoint(ctx: agents.JobContext):
    session = AgentSession(
        stt=gradium.STT(),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=gradium.TTS(voice_id="<your-cloned-voice-id>"),
        vad=silero.VAD.load(),  # or gradium VAD if available
        noise_cancellation=aicoustics.NoiseCancellation(),
        preemptive_generation=True,
    )
    await session.start(agent=ClaimsAgent(), room=ctx.room)
    await session.generate_reply(
        instructions="Greet the caller naturally — like a real adjuster picking up the phone."
    )

if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))