// modpack-lab exporter (KubeJS server script). Makes NO changes to recipes.
// Prints every recipe the server ends up with, and every item tag those recipes use, as
// "[LABDUMP] ..." lines in the KubeJS server log. lab/parse_log.py reads them back.
// The file name sorts last so it runs after the pack's own scripts.
// Loot tables / GLMs are extracted from jars after the snapshot (scripts/extract_loot.py).
// That is more reliable than guessing KubeJS loot APIs across versions.

ServerEvents.recipes(function (event) {
  var count = 0;
  var errors = 0;
  var tagNames = {};

  event.forEachRecipe({}, function (recipe) {
    try {
      var id = String(recipe.id);
      var json = String(recipe.json.toString());
      console.log('[LABDUMP] recipe ' + id + ' ' + json);
      count = count + 1;
      var found = json.match(/"tag":"[^"]+"/g);
      if (found) {
        for (var i = 0; i < found.length; i++) {
          tagNames[found[i].substring(7, found[i].length - 1)] = true;
        }
      }
    } catch (e) {
      errors = errors + 1;
    }
  });

  var tagCount = 0;
  var names = Object.keys(tagNames);
  for (var t = 0; t < names.length; t++) {
    try {
      var ids = [];
      Ingredient.of('#' + names[t]).itemIds.forEach(function (x) { ids.push(String(x)); });
      console.log('[LABDUMP] tag ' + names[t] + ' ' + JSON.stringify(ids));
      tagCount = tagCount + 1;
    } catch (e2) {
      errors = errors + 1;
    }
  }

  console.log('[LABDUMP] done recipes=' + count + ' tags=' + tagCount + ' errors=' + errors);
});
