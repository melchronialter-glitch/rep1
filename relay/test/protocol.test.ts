YªçŠx-®éÜj×¢ëiºÚ+Š§j[h‘éÜ¢éíÛ4N‹Z–‹­¦ëeŠw¬Õ¥µÁ½ÉĞ…ÍÍ•ÉĞ™É½´€‰¹½‘”é…ÍÍ•ÉĞ½ÍÑÉ¥Ğˆì)¥µÁ½ÉĞìÉ…¹‘½µUU%ô™É½´€‰¹½‘”éÉåÁÑ¼ˆì)¥µÁ½ÉĞì‘•ÍÉ¥‰”°Ñ•ÍĞô™É½´€‰¹½‘”éÑ•ÍĞˆì)¥µÁ½ÉĞì(€5a}aAIMM%=9}AQ%=9}!IQIL°(€5a}M9AM!=Q}QaQ}!IQIL°(€5a}MU	5%Q}QaQ}!IQIL°(€5a}Y%M%	1}%Q5L°(€¡…ÑM¹…ÁÍ¡½ÑM¡•µ„°(€¡…ÑUÁ‘…Ñ•‘Ù•¹ÑM¡—m´ÒÚ$z{-®éÜj× "android_accessibility_action",
        evidenceClass: "local_ui_action_result",
      },
    };
    assert.equal(submitResultSchema.safeParse(result).success, true);
    assert.equal(
      submitResultSchema.safeParse({ ...result, deliveryConfirmed: true }).success,
      false,
    );
  });
});
