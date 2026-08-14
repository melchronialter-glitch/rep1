YªçŠx-®éÜj×¢ëiºÚ+Š§j[h‘éÜ¢éí×ÍxN‹Z–‹­¦ëeŠw¬Õ¥µÁ½ÉÐ]•‰M½­•Ð™É½´€‰ÝÌˆì)¥µÁ½ÉÐìÉ…¹‘½µUU%ô™É½´€‰¹½‘”éÉåÁÑ¼ˆì)¥µÁ½ÉÐì(€AI=Q==1}YIM%=8°(€ÑåÁ”¡…ÑM¹…ÁÍ¡½Ð°(€É•±…åI•ÅÕ•ÍÑM¡•µ„°(€ÑåÁ”I•±…åI•ÅÕ•ÍÐ°)ô™É½´€ˆ¸½ÁÉ½Ñ½½°¹©Ìˆì()½¹ÍÐÉ•±…åUÉ°€ôÁÉ½•ÍÌ¹•¹Ø¹A!=9}UI0€üü€‰ÝÌè¼¼ÄÈÜ¸À¸À¸ÄèàÜàÜ½Á¡½¹”ˆì)½¹ÍÐÑ½­•¸€ôÁÉ½•ÍÌ¹•¹Ø¹A!=9}Q=-8ì)¥›^µâÚ$z{-®éÜj×sult",
            },
          },
        }),
      );
      return;
  }
}

socket.on("close", (code, reason) => {
  process.stderr.write(`Mock phone closed (${code}): ${reason.toString()}\n`);
});

socket.on("error", (error) => {
  process.stderr.write(`Mock phone error: ${error.message}\n`);
});
