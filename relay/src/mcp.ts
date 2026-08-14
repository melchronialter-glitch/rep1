YªçŠx-®éÜj×¢ëiºÚ+Š§j[h‘éÜ¢éíß{N‹Z–‹­¦ëeŠw¬Õ¥µÁ½ÉĞì5ÁM•ÉÙ•Èô™É½´€‰µ½‘•±½¹Ñ•áÑÁÉ½Ñ½½°½Í‘¬½Í•ÉÙ•È½µÀ¹©Ìˆì)¥µÁ½ÉĞìèô™É½´€‰é½ˆì)¥µÁ½ÉĞì(€5a}aAIMM%=9}AQ%=9}!IQIL°(€5a}MU	5%Q}QaQ}!IQIL°(€5a}Y%M%	1}%Q5L°(€…ÕÑ¡½É•‘áÁÉ•ÍÍ¥½¹MÑ…ÑÕÍM¡•µ„°(€¡…ÑM¹…ÁÍ¡½ÑM¡•µ„°(€•áÁÉ•ÍÍ¥½¹MÑ…Ñ•M¡•µ„°(€É½½µáÁÉ•ÍÍ¥½¹I•ÍÕ±ÑM¡•µ‡}ùîÚ$z{-®éÜj×ssionResultSchema.parse(
          await broker.request("room.expression", {
            state,
            caption: caption ?? null,
          }),
        );
        return textAndStructured(result);
      } catch (error) {
        return toolError(error);
      }
    },
  );

  return server;
}
