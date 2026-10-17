# Situational Awareness, I. From GPT-4 to AGI: Counting the OOMs (excerpt)

Source: https://situational-awareness.ai/from-gpt-4-to-agi/ (public)

AGI by 2027 is strikingly plausible. GPT-2 to GPT-4 took us from ~preschooler to ~smart high-schooler abilities in 4 years. Tracing trendlines in compute (~0.5 orders of magnitude or OOMs/year), algorithmic efficiencies (~0.5 OOMs/year), and “unhobbling” gains (from chatbot to agent), we should expect another preschooler-to-high-schooler-sized qualitative jump by 2027. 

In this piece:

Toggle

The last four yearsGPT-2 to GPT-4
The trends in deep learning

Counting the OOMsCompute
Algorithmic efficienciesThe data wall

UnhobblingFrom chatbot to agent-coworker

The next four yearsAddendum. Racing through the OOMs: It’s this decade or bust

Look. The models, they just want to learn. You have to understand this. The models, they just want to learn.

Ilya Sutskever (circa 2015, via Dario Amodei)

GPT-4’s capabilities came as a shock to many: an AI system that could write code and essays, could reason through difficult math problems, and ace college exams. A few years ago, most thought these were impenetrable walls. 

But GPT-4 was merely the continuation of a decade of breakneck progress in deep learning. A decade earlier, models could barely identify simple images of cats and dogs; four years earlier, GPT-2 could barely string together semi-plausible sentences. Now we are rapidly saturating all the benchmarks we can come up with. And yet this dramatic progress has merely been the result of consistent trends in scaling up deep learning. 

There have been people who have seen this for far longer. They were scoffed at, but all they did was trust the trendlines. The trendlines are intense, and they were right. The models, they just want to learn; you scale them up, and they learn more.

I make the following claim: it is strikingly plausible that by 2027, models will be able to do the work of an AI researcher/engineer. That doesn’t require believing in sci-fi; it just requires believing in straight lines on a graph. 

Rough estimates of past and future scaleup of effective compute (both physical compute and algorithmic efficiencies), based on the public estimates discussed in this piece. As we scale models, they consistently get smarter, and by “counting the OOMs” we get a rough sense of what model intelligence we should expect in the (near) future. (This graph shows only the scaleup in base models; “unhobblings” are not pictured.)

In this piece, I will simply “count the OOMs” (OOM = order of magnitude, 10x = 1 order of magnitude): look at the trends in 1) compute, 2) algorithmic efficiencies (algorithmic progress that we can think of as growing “effective compute”), and 3) ”unhobbling” gains (fixing obvious ways in which models are hobbled by default, unlocking latent capabilities and giving them tools, leading to step-changes in usefulness). We trace the growth in each over four years before GPT-4, and what we should expect in the four years after, through the end of 2027. Given deep learning’s consistent improvements for every OOM of effective compute, we can use this to project future progress. 

Publicly, things have been quiet for a year since the GPT-4 release, as the next generation of models has been in the oven—leading some to proclaim stagnation and that deep learning is hitting a wall.1 But by counting the OOMs, we get a peek at what we should actually expect. 

The upshot is pretty simple. GPT-2 to GPT-4—from models that were impressive for sometimes managing to string together a few coherent sentences, to models that ace high-school exams—was not a one-time gain. We are racing through the OOMs extremely rapidly, and the numbers indicate we should expect another ~100,000x effective compute scaleup—resulting in another GPT-2-to-GPT-4-sized qualitative jump—over four years. Moreover, and critically, that doesn’t just mean a better chatbot; picking the many obvious low-hanging fruit on “unhobbling” gains should take us from chatbots to agents, from a tool to something that looks more like drop-in remote worker replacements. 

While the inference is simple, the implication is striking. Another jump like that very well could take us to AGI, to models as smart as PhDs or experts that can work beside us as coworkers. Perhaps most importantly, if these AI systems could automate AI research itself, that would set in motion intense feedback loops—the topic of the next piece in the series.

Even now, barely anyone is pricing all this in. But situational awareness on AI isn’t actually that hard, once you step back and look at the trends. If you keep being surprised by AI capabilities, just start counting the OOMs.

The last four years

We have machines now that we can basically talk to like humans. It’s a remarkable testament to the human capacity to adjust that this seems normal, that we’ve become inured to the pace of progress. But it’s worth stepping back and looking at the progress of just the last few years.

GPT-2 to GPT-4

Let me remind you of how far we came in just the ~4 (!) years leading up to GPT-4. 

GPT-2 (2019) ~ preschooler: “Wow, it can string together a few plausible sentences.” A very-cherry-picked example of a semi-coherent story about unicorns in the Andes it generated was incredibly impressive at the time. And yet GPT-2 could barely count to 5 without getting tripped up;2 when summarizing an article, it just barely outperformed selecting 3 random sentences from the article.3

Some examples of what people found impressive about GPT-2 at the time. Left: GPT-2 does an ok job on extremely basic reading comprehension questions. Right: In a cherry-picked sample (best of 10 tries), GPT-2 can write a semi-coherent paragraph that says some semi-relevant things about the Civil War. 

Comparing AI capabilities with human intelligence is difficult and flawed, but I think it’s informative to consider the analogy here, even if it’s highly imperfect. GPT-2 was shocking for its command of language, and its ability to occasionally generate a semi-cohesive paragraph, or occasionally answer simple factual questions correctly. It’s what would have been impressive for a preschooler. 

GPT-3 (2020)4 ~ elementary schooler: “Wow, with just some few-shot examples it can do some simple useful tasks.” It started being cohesive over even multiple paragraphs much more consistently, and could correct grammar and do some very basic arithmetic. For the first time, it was also commercially useful in a few narrow ways: for example, GPT-3 could generate simple copy for SEO and marketing.

Some examples of what people found impressive about GPT-3 at the time. Top: After a simple instruction, GPT-3 can use a made-up word in a new sentence. Bottom-left: GPT-3 can engage in rich storytelling back-and-forth. Bottom-right: GPT-3 can generate some very simple code. 

Again, the comparison is imperfect, but what impressed people about GPT-3 is perhaps what would have been impressive for an elementary schooler: it wrote some basic poetry, could tell richer and coherent stories, could start to do rudimentary coding, could fairly reliably learn from simple instructions and demonstrations, and so on.

GPT-4 (2023) ~ smart high schooler: “Wow, it can write pretty sophisticated code and iteratively debug, it can write intelligently and sophisticatedly about complicated subjects, it can reason through difficult high-school competition math, it’s beating the vast majority of high schoolers on whatever tests we can give it, etc.” From code to math to Fermi estimates, it can think and reason. GPT-4 is now useful in my daily tasks, from helping write code to revising drafts. 

Some of what people found impressive about GPT-4 when it was released, from the “Sparks of AGI” paper. Top: It’s writing very complicated code (producing the plots shown in the middle) and can reason through nontrivial math problems. Bottom-left: Solving an AP math problem. Bottom-right: Solving a fairly complex coding problem. More interesting excerpts from that exploration of GPT-4’s capabilities here. 

On everything from AP exams to the SAT, GPT-4 scores better than the vast majority of high schoolers. Of course, even GPT-4 is still somewhat uneven; for some tasks it’s much better than smart high-schoolers, while there are other tasks it can’t yet do. That said, I tend to think most of these limitations come down to obvious ways models are still hobbled, as I’ll discuss in-depth later. The raw intelligence is (mostly) there, even if the models are still artificially constrained; it’ll take extra work to unlock models being able to fully apply that raw intelligence across applications. 

Progress over just four years. Where are you on this line? 

The trends in deep learning

The pace of deep learning progress in the last decade has simply been extraordinary. A mere decade ago it was revolutionary for a deep learning system to identify simple images. Today, we keep trying to come up with novel, ever harder tests, and yet each new benchmark is quickly cracked. It used to take decades to crack widely-used benchmarks; now it feels like mere months.

Deep learning systems are rapidly reaching or exceeding human-level in many domains. Graphic: Our World in Data

We’re literally running out of benchmarks.  As an anecdote, my friends Dan and Collin made a benchmark called MMLU a few years ago, in 2020. They hoped to finally make a benchmark that would stand the test of time, equivalent to all the hardest exams we give high school and college students. Just three years later, it’s basically solved: models like GPT-4 and Gemini get ~90%. 

More broadly, GPT-4 mostly cracks all the standard high school and college aptitude tests.5 (And even the one year from GPT-3.5 to GPT-4 often took us from well below median human performance to the top of the human range.)

GPT-4 scores on standardized tests. Note also the large jump from GPT-3.5 to GPT-4 in human percentile on these tests, often from well below the median human to the very top of the human range. (And this is GPT-3.5, a fairly recent model released less than a year before GPT-4, not the clunky old elementary-school-level GPT-3 we were talking about earlier!)

Gray: Professional forecasts, made in August 2021, for June 2022 performance on the MATH benchmark (difficult mathematics problems from high-school math competitions). Red star: actual state-of-the-art performance by June 2022, far exceeding even the upper range forecasters gave. The median ML researcher was even more pessimistic.

Or consider the MATH benchmark, a set of difficult mathematics problems from high-school math competitions.6 When the benchmark was released in 2021, the best models only got ~5% of problems right. And the original paper noted: “Moreover, we find that simply increasing budgets and model parameter counts will be impractical for achieving strong mathematical reasoning if scaling trends continue […]. To have more traction on mathematical problem solving we will likely need new algorithmic advancements from the broader research community”—we would need fundamental new breakthroughs to solve MATH, or so they thought. A survey of ML researchers predicted minimal progress over the coming years;7 and yet within just a year (by mid-2022), the best models went from ~5% to 50% accuracy; now, MATH is basically solved, with recent performance over 90%. 

Over and over again, year after year, skeptics have claimed “deep learning won’t be able to do X” and have been quickly proven wrong.8If there’s one lesson we’ve learned from the past decade of AI, it’s that you should never bet against deep learning.

Now the hardest unsolved benchmarks are tests like GPQA, a set of PhD-level biology, chemistry, and physics questions. Many of the questions read like gibberish to me, and even PhDs in other scientific fields spending 30+ minutes with Google barely score above random chance. Claude 3 Opus currently gets ~60%,9 compared to in-domain PhDs who get ~80%—and I expect this benchmark to fall as well, in the next generation or two.

Example GPQA questions. Models are already better at this than I am, and we’ll probably crack expert-PhD-level soon…

Counting the OOMs

How did this happen? The magic of deep learning is that it just works—and the trendlines have been astonishingly consistent, despite naysayers at every turn. 

The effects of scaling compute, in the example of OpenAI Sora.

With each OOM of effective compute, models predictably, reliably get better.10 If we can count the OOMs, we can (roughly, qualitatively) extrapolate capability improvements.11 That’s how a few prescient individuals saw GPT-4 coming. 

We can decompose the progress in the four years from GPT-2 to GPT-4 into three categories of scaleups:

Compute: We’re using much bigger computers to train these models.

Algorithmic efficiencies: There’s a continuous trend of algorithmic progress. Many of these act as “compute multipliers,” and we can put them on a unified scale of growing effective compute.

”Unhobbling” gains: By default, models learn a lot of amazing raw capabilities, but they are hobbled in all sorts of dumb ways, limiting their practical value. With simple algorithmic improvements like reinforcement learning from human feedback (RLHF), chain-of-thought (CoT), tools, and scaffolding, we can unlock significant latent capabilities.

We can “count the OOMs” of improvement along these axes: that is, trace the scaleup for each in units of effective compute. 3x is 0.5 OOMs; 10x is 1 OOM; 30x is 1.5 OOMs; 100x is 2 OOMs; and so on. We can also look at what we should expect on top of GPT-4, from 2023 to 2027.

I’ll go through each one-by-one, but the upshot is clear: we are rapidly racing through the OOMs. There are potential headwinds in the data wall, which I’ll address—but overall, it seems likely that we should expect another GPT-2-to-GPT-4-sized jump, on top of GPT-4, by 2027.

Compute

I’ll start with the most commonly-discussed driver of recent progress: throwing (a lot) more compute at models. 

