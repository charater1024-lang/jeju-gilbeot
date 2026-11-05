import json,sqlite3,tempfile,unittest
from pathlib import Path
from jeju_agent.roads import build_roads,astar,nearest,_graph
class RoadTests(unittest.TestCase):
    def test_oneway_and_explicit_access_and_barriers_use_real_topology(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            root=Path(folder);(root/'data_raw/osm').mkdir(parents=True)
            elements=[{'type':'node','id':i,'lat':33.5,'lon':126.5+i*.001} for i in range(1,6)]
            elements += [{'type':'way','id':10,'nodes':[1,2,3],'tags':{'highway':'residential','oneway':'yes'}},{'type':'way','id':11,'nodes':[3,4],'tags':{'highway':'service','access':'private'}},{'type':'way','id':12,'nodes':[3,5],'tags':{'highway':'residential','oneway':'-1'}}]
            (root/'data_raw/osm/jeju_roads_v5.json').write_text(json.dumps({'elements':elements}),encoding='utf-8')
            p=build_roads(root);self.assertEqual(p['ways_excluded'],1)
            points,adj,cells=_graph(root)
            self.assertEqual(astar(1,3,points,adj)[0],[1,2,3]);self.assertIsNone(astar(3,1,points,adj)[0]);self.assertEqual(astar(5,3,points,adj)[0],[5,3]);self.assertNotIn(4,points)
            self.assertIsNone(nearest((33.1,126.1),points,cells)[0])
    def test_astar_does_not_invent_disconnected_edges(self):
        points={1:(33.5,126.5),2:(33.51,126.51),3:(33.52,126.52)}
        self.assertIsNone(astar(1,3,points,{1:[(2,1)],2:[],3:[]})[0])
