function [G, graphHandle] = buildCallGraph(ax, callSequence, options)
% BUILDCALLGRAPH Build and plot a directed call graph from the call sequence.
%
%   [G, graphHandle] = buildCallGraph(ax, callSequence)
%   [G, graphHandle] = buildCallGraph(ax, callSequence, options)
%
%   Inputs:
%     ax           - Target axes handle
%     callSequence - struct array from parseProfilerPhases
%     options      - (optional) struct with fields:
%       .highlightName - function name to highlight (default: '')
%       .layout        - graph layout: 'layered', 'force', 'circle' (default: 'layered')
%       .maxNodes      - maximum number of nodes to display (default: 100)
%
%   Outputs:
%     G           - digraph object
%     graphHandle - handle to the graph plot

    if nargin < 3
        options = struct();
    end

    highlightName = getOpt(options, 'highlightName', '');
    layoutType    = getOpt(options, 'layout', 'layered');
    maxNodes      = getOpt(options, 'maxNodes', 100);

    cla(ax);

    if isempty(callSequence)
        title(ax, 'No data to display');
        G = digraph();
        graphHandle = [];
        return;
    end

    % Build edge list from consecutive enter events (caller -> callee)
    % We track the call stack to determine caller-callee relationships.
    callStack = {};  % stack of function names
    edgeMap = containers.Map();  % 'caller->callee' -> count

    for k = 1:numel(callSequence)
        entry = callSequence(k);
        if strcmp(entry.event, 'enter')
            if ~isempty(callStack)
                caller = callStack{end};
                callee = entry.funcName;
                edgeKey = [caller, '->', callee];
                if edgeMap.isKey(edgeKey)
                    edgeMap(edgeKey) = edgeMap(edgeKey) + 1;
                else
                    edgeMap(edgeKey) = 1;
                end
            end
            callStack{end+1} = entry.funcName; %#ok<AGROW>
        elseif strcmp(entry.event, 'exit') && ~isempty(callStack)
            % Pop from stack (find matching name from top)
            for s = numel(callStack):-1:1
                if strcmp(callStack{s}, entry.funcName)
                    callStack(s) = [];
                    break;
                end
            end
        end
    end

    if edgeMap.Count == 0
        title(ax, 'No call relationships found');
        G = digraph();
        graphHandle = [];
        return;
    end

    % Parse edge map into source/target/weight arrays
    keys = edgeMap.keys();
    nEdges = numel(keys);
    sources = cell(nEdges, 1);
    targets = cell(nEdges, 1);
    weights = zeros(nEdges, 1);

    for k = 1:nEdges
        parts = strsplit(keys{k}, '->');
        sources{k} = parts{1};
        targets{k} = parts{2};
        weights(k) = edgeMap(keys{k});
    end

    % Build the digraph
    edgeTable = table(sources, targets, weights, ...
        'VariableNames', {'EndNodes1', 'EndNodes2', 'Weight'});
    G = digraph(sources, targets, weights);

    % If too many nodes, keep only the top N by total edge weight
    if numnodes(G) > maxNodes
        nodeNames = G.Nodes.Name;
        nodeWeights = zeros(numel(nodeNames), 1);
        for k = 1:numel(nodeNames)
            nodeWeights(k) = sum(weights(strcmp(sources, nodeNames{k}))) + ...
                             sum(weights(strcmp(targets, nodeNames{k})));
        end
        [~, sortIdx] = sort(nodeWeights, 'descend');
        keepNodes = nodeNames(sortIdx(1:maxNodes));
        removeNodes = setdiff(nodeNames, keepNodes);
        G = rmnode(G, removeNodes);
    end

    % Plot
    hold(ax, 'on');

    graphHandle = plot(ax, G, 'Layout', layoutType, ...
        'EdgeLabel', G.Edges.Weight, ...
        'NodeFontSize', 8, ...
        'EdgeFontSize', 7, ...
        'ArrowSize', 8, ...
        'Interpreter', 'none');

    % Scale edge widths by weight
    maxWeight = max(G.Edges.Weight);
    if maxWeight > 0
        scaledWidths = 0.5 + 3.5 * (G.Edges.Weight / maxWeight);
        graphHandle.LineWidth = scaledWidths;
    end

    % Highlight specific node if requested
    if ~isempty(highlightName)
        nodeNames = G.Nodes.Name;
        matchIdx = find(contains(nodeNames, highlightName, 'IgnoreCase', true));
        if ~isempty(matchIdx)
            highlight(graphHandle, matchIdx, 'NodeColor', [1 0 0], 'MarkerSize', 10);
        end
    end

    % Color all nodes by degree
    nodeColors = repmat([0.2 0.5 0.8], numnodes(G), 1);
    graphHandle.NodeColor = nodeColors;

    % Re-apply highlight after setting NodeColor
    if ~isempty(highlightName)
        nodeNames = G.Nodes.Name;
        matchIdx = find(contains(nodeNames, highlightName, 'IgnoreCase', true));
        if ~isempty(matchIdx)
            highlight(graphHandle, matchIdx, 'NodeColor', [1 0 0], 'MarkerSize', 10);
        end
    end

    title(ax, sprintf('Call Graph (%d nodes, %d edges)', numnodes(G), numedges(G)));
    hold(ax, 'off');
end

function val = getOpt(opts, fieldName, default)
    if isfield(opts, fieldName)
        val = opts.(fieldName);
    else
        val = default;
    end
end
