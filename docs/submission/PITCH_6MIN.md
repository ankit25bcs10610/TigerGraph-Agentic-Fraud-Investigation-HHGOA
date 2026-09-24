# Sentinel: 6-minute pitch

Speak slowly. Pause where there is a blank line. About 780 words, which is six minutes with the screen changes.

Open the app first, restart the API so every case starts as *New*, and keep these ready: the command center, HHG-016, HHG-014, the Fraud rings tab, HHG-011, HHG-010.

---

## 0:00 – 1:00 · Why it matters, one case, our answer

**Screen:** the command center.

> Fraud is never alone.
>
> Hi, we're Kartikeya and Ankit, and this is Sentinel.
>
> A bank's fraud team gets more alerts than they can ever check. Block too fast, and honest customers get their cards frozen. Move too slow, and the money is gone. And fraud rings use many cards at once, so every alert is only one small piece of a bigger picture.
>
> Here's one piece. A customer writes in: "I never made this $59.67 purchase." It's a small amount. Most teams would refund it and move on.
>
> But that card is one of 36 cards, used on the same shared devices, all making small online purchases. Two weeks later, another customer reports the same thing. Nobody connects them.
>
> Sentinel does. It's an AI agent that investigates every alert on TigerGraph, the way a careful analyst would. It follows the connections, it knows when it doesn't have enough evidence, and it never blocks a card without a human saying yes.

## 1:00 – 1:45 · How it works

**Screen:** stay on the command center, then open **HHG-016**.

> An alert opens a case. The agent asks the graph questions, one at a time, and writes down why it asked each one. Every question is a GSQL query, called through TigerGraph's official MCP server.
>
> Then it scores the evidence with clear rules, not a black box. If the evidence isn't enough, it stops and asks the customer, or asks for extra verification. Then it recommends what to do, using the bank's own policy. Anything serious, like blocking a card, waits for a person to approve it.

## 1:45 – 2:40 · A live case

**Screen:** HHG-016, the **Agent reasoning** panel. Point at the device step, then the ring step.

> This is that $59.67 case, running live.
>
> Look here. The device on this purchase was used by 158 different people. A simple system would shout: shared device, fraud ring!
>
> Our agent checks first. The profile only says "Windows, Edge browser". That's not one device. That's thousands of normal laptops. So it skips it, and it writes down why.
>
> Then look here. It checks the whole graph instead, and finds this card inside a ring of 36 cards. Same ring, found a different way. Six seconds, all on TigerGraph.

## 2:40 – 3:25 · The mistake that made it smart

**Screen:** open **HHG-014**, point at the device evidence.

> Honestly, we learned this the hard way. Our first version found fraud rings everywhere. Thirteen out of twenty cases. One "ring" had over six thousand customers.
>
> The reason? A new Chrome version. Hundreds of people started using it in the same month, and our agent thought that was a crime.
>
> So now it asks three simple questions about every device. How many people used it? How many used it this week? And is it a real phone model, or just "Windows"?
>
> That's how it catches this one: one Samsung phone, used by 24 different customers in a single week. The analyst's request in the challenge asked about exactly this.

## 3:25 – 4:10 · Hidden rings, and memory

**Screen:** the **Fraud rings** tab, then open **HHG-011** and point at `recall_graph_memory`.

> Across all 590,000 transactions, the agent found eight rings, and it describes each one in plain words. The biggest: 36 cards on 16 shared devices, all online, almost all the same product. None of the known fraud patterns look like that. That's the hidden pattern the challenge warned us about.
>
> And it remembers. Every case it finishes is saved back into TigerGraph. When it opens this case on December 29th, it recalls its own finding from December 12th: a different customer, but a card in the same ring. It only ever learns from the past, never from the future.

## 4:10 – 5:00 · When it's not sure

**Screen:** open **HHG-010** → Decision paths → record the customer's answer → Decisions → Audit.

> Now, what if the evidence isn't clear? This is a thousand-dollar alert, and the graph can't decide. So the agent doesn't guess.
>
> Before asking anything, it plays out every possible answer, and asks the question that would change the decision the most.
>
> When the answer comes in, the recommendation updates. You can see before and after, side by side.
>
> Blocking a card needs an L1 or L2 approval. And every single step is sealed in a hash chain that your browser checks, right here: case record verified.

## 5:00 – 5:35 · Does it work?

**Screen:** the README's "On the live graph" table, or `outputs/benchmark_final/REPORT.md`.

> So, does it work? All 20 benchmark cases ran live on TigerGraph, and all 20 were saved back to the graph.
>
> Fake rings went from 13 cases down to 3, and each of those 3 has proof an analyst can check. The biggest "ring" behind one alert went from 6,322 customers to 38.
>
> We're honest about the rest too. The full numbers, good and bad, are in our blog.

## 5:35 – 6:00 · Close

**Screen:** back to the command center.

> Fraud is never alone, and now, neither is your analyst.
>
> Sentinel follows the connections, knows when it isn't sure, and leaves a record anyone can check.
>
> Thank you.

---

**Tips:** record your voice separately if the room is noisy. If a screen loads slowly, keep talking and cut the wait later. If you run long, shorten "Does it work?" first, never the opening.
