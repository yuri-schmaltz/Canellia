// Frozen pre-optimization search semantics for differential regressions.
const searchStrPart = (q, str, noFuzzySearch, noSubStringSearch) => {
    if (!str || !q) {
        return 0; //match score = 0
    }

    const str2 = graphemeBaseChars(str).toLocaleUpperCase();
    //q is already graphemeBaseChars().toLocaleUpperCase() in _doSearch()
    let score = 0, bigrams_score = 0;

    if (new RegExp('\\b'+escapeRegExp(q)).test(str2)) { //match substring from beginning of words
        const foundPosition = str2.indexOf(q);
        score = (foundPosition === 0) ? 1.21 : 1.2;//slightly higher score if from beginning
    } else if (!noSubStringSearch && str2.indexOf(q) !== -1) { //else match substring
        score = 1.1;
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

            //return a fuzzy match score of between 0 and 1.
            score = Math.min(longest.length / q.length, 1.0) * bigrams_score;
        }
    }

    return score;
};

const searchStr = (q, str, noFuzzySearch = false, noSubStringSearch = false) => {
    if (q && str && graphemeBaseChars(str).toLocaleUpperCase() === q) return 1.5;
    const separatorIndex = q.indexOf(" ");
    if (separatorIndex < 1) {
        return searchStrPart(q, str, noFuzzySearch, noSubStringSearch);
    }

    //There are two search terms separated by a space.
    const part1Score = searchStrPart(q.slice(0, separatorIndex), str, noFuzzySearch, noSubStringSearch);
    const part2Score = searchStrPart(q.slice(separatorIndex + 1), str, noFuzzySearch, noSubStringSearch);
    const avgScore = (part1Score + part2Score) / 2.0;

    return avgScore;
};


module.exports = {searchStr};
