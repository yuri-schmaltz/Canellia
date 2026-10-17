// Frozen pre-optimization search semantics for differential regressions.
const searchStrPart = (q, str, noFuzzySearch, noSubStringSearch) => {
    if (!str || !q) {
        return { score: 0, result: str };
    }

    const HIGHTLIGHT_MATCH = true;
    let foundPosition = 0;
    let foundLength = 0;
    const str2 = graphemeBaseChars(str).toLocaleUpperCase();
    //q is already graphemeBaseChars().toLocaleUpperCase() in _doSearch()
    let score = 0, bigrams_score = 0;

    if (new RegExp('\\b'+escapeRegExp(q)).test(str2)) { //match substring from beginning of words
        foundPosition = str2.indexOf(q);
        score = (foundPosition === 0) ? 1.21 : 1.2;//slightly higher score if from beginning
        foundLength = q.length;
    } else if (!noSubStringSearch && str2.indexOf(q) !== -1) { //else match substring
        score = 1.1;
        foundPosition = str2.indexOf(q);
        foundLength = q.length;
    } else if (!noFuzzySearch){ //else fuzzy match
        //find longest substring of str2 made up of letters from q
        const found = str2.match(new RegExp('[' + escapeRegExp(q) + ']+','g'));
        let length = 0;
        let longest;
        if (found) {
            for(let i=0; i < found.length; i++){
                if(found[i].length > length){
                    length = found[i].length;
                    longest = found[i];
                }
            }
        }
        if (longest) {
            //get a score for similarity by counting 2 letter pairs (bigrams) that match
            if (q.length >= 2) {
                const max_bigrams = q.length -1;
                let found_bigrams = 0;
                for (let qi = 0; qi < max_bigrams; qi++ ) {
                    if (longest.indexOf(q[qi] + q[qi + 1]) >= 0) {
                        found_bigrams++;
                    }
                }
                bigrams_score = Math.min(found_bigrams / max_bigrams, 1);
            } else {
                bigrams_score = 1;
            }

            foundPosition = str2.indexOf(longest);
            foundLength = longest.length;
            //return a fuzzy match score of between 0 and 1.
            score = Math.min(longest.length / q.length, 1.0) * bigrams_score;
        }
    }

    //reduce score if q is short
    //if (q.length === 1) score *= 0.5;
    //if (q.length === 2) score *= 0.75;
    //return result of match

    if (HIGHTLIGHT_MATCH && score > 0) {
        let markup = str.slice(0, foundPosition) + '<b>' +
                                    str.slice(foundPosition, foundPosition + foundLength) + '</b>' +
                                                    str.slice(foundPosition + foundLength, str.length);
        return {score: score, result: markup};
    } else {
        return {score: score, result: str};
    }
};

const searchStr = (q, str, noFuzzySearch = false, noSubStringSearch = false) => {
    if (q && str && graphemeBaseChars(str).toLocaleUpperCase() === q)
        return {score: 1.5, result: '<b>' + str + '</b>'};
    const separatorIndex = q.indexOf(" ");
    if (separatorIndex < 1) {
        return searchStrPart(q, str, noFuzzySearch, noSubStringSearch);
    }

    //There are two search terms separated by a space.
    const part1 = searchStrPart(q.slice(0, separatorIndex), str, noFuzzySearch, noSubStringSearch);
    const part2 = searchStrPart(q.slice(separatorIndex + 1), str, noFuzzySearch, noSubStringSearch);
    const avgScore = (part1.score + part2.score) / 2.0;
    const markup = (part1.score >= part2.score) ? part1.result : part2.result;

    return {score: avgScore, result: markup};
};


module.exports = {searchStr};
