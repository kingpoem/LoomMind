"""LangGraph Agent：支持工具调用的多节点图。"""

from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from api import create_chat_model
from skills import load_all_skills
from skills.business_funcs import check_banned_words
from tools.loader import load_tools


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


def build_graph():
    tools = [*load_tools(), *load_all_skills()]
    print(f"Loaded {len(tools)} tools.")
    model = create_chat_model()
    if tools:
        model = model.bind_tools(tools)

    def agent(state: AgentState) -> dict:
        last = state["messages"][-1] if state.get("messages") else None
        if isinstance(last, HumanMessage) and isinstance(last.content, str):
            if check_banned_words(last.content):
                return {"messages": [AIMessage(content="让我们换个话题")]}
        reply: AIMessage = model.invoke(state["messages"])
        return {"messages": [reply]}

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return END

    g = StateGraph(AgentState)
    g.add_node("agent", agent)
    g.add_edge(START, "agent")

    if tools:
        g.add_node("tools", ToolNode(tools))
        g.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
        g.add_edge("tools", "agent")
    else:
        g.add_edge("agent", END)

    return g.compile()
